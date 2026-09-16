"""Tests for subscription lag monitoring core module.

Tests cover the SubscriptionStatus dataclass, collection functions,
stream category inference, classification helpers, and graceful degradation
when infrastructure is unavailable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from protean.server.subscription_status import (
    SubscriptionStatus,
    _classify_status,
    _collect_broker_status,
    _collect_event_store_status,
    _collect_outbox_statuses,
    _collect_stream_status,
    _infer_stream_category,
    _lag_seconds,
    _unknown_status,
    collect_subscription_statuses,
)
from protean.utils.eventing import MessageType

# ---------------------------------------------------------------------------
# SubscriptionStatus dataclass
# ---------------------------------------------------------------------------


class TestSubscriptionStatusDataclass:
    def test_to_dict_returns_all_fields(self):
        status = SubscriptionStatus(
            name="handler-1",
            handler_name="OrderProjector",
            subscription_type="event_store",
            stream_category="order",
            lag=5,
            pending=0,
            current_position="10",
            head_position="15",
            status="lagging",
            consumer_count=0,
            dlq_depth=0,
        )
        d = status.to_dict()
        assert d["name"] == "handler-1"
        assert d["handler_name"] == "OrderProjector"
        assert d["subscription_type"] == "event_store"
        assert d["stream_category"] == "order"
        assert d["lag"] == 5
        assert d["pending"] == 0
        assert d["current_position"] == "10"
        assert d["head_position"] == "15"
        assert d["status"] == "lagging"
        assert d["consumer_count"] == 0
        assert d["dlq_depth"] == 0
        assert "last_updated" in d
        assert d["last_updated"] is None
        assert "lag_seconds" in d
        assert d["lag_seconds"] is None

    def test_to_dict_with_none_lag(self):
        status = SubscriptionStatus(
            name="handler-1",
            handler_name="Handler",
            subscription_type="stream",
            stream_category="test",
            lag=None,
            pending=0,
            current_position=None,
            head_position=None,
            status="unknown",
            consumer_count=0,
            dlq_depth=0,
        )
        d = status.to_dict()
        assert d["lag"] is None
        assert d["status"] == "unknown"


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


class TestClassifyStatus:
    def test_ok_when_zero_lag_and_zero_pending(self):
        assert _classify_status(0, 0) == "ok"

    def test_lagging_when_lag_positive(self):
        assert _classify_status(5) == "lagging"

    def test_lagging_when_pending_positive(self):
        assert _classify_status(0, 3) == "lagging"

    def test_unknown_when_lag_is_none(self):
        assert _classify_status(None) == "unknown"


class TestLagSeconds:
    def test_positive_lag_reports_seconds_behind(self):
        """A lagging subscription reports wall-clock seconds since last update."""
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        last_updated = (now - timedelta(seconds=42)).isoformat()
        assert _lag_seconds(5, last_updated, now) == pytest.approx(42.0)

    def test_caught_up_is_zero_without_touching_now(self):
        """``lag == 0`` is 0.0 and never does datetime arithmetic on ``now``."""
        assert _lag_seconds(0, None, MagicMock()) == 0.0

    def test_unknown_lag_is_none(self):
        """``lag is None`` (unreadable) reports ``None`` seconds, not 0.0."""
        assert _lag_seconds(None, "2026-01-01T12:00:00Z", MagicMock()) is None

    def test_missing_last_updated_is_none_not_zero(self):
        """Lagging with no timestamp is unavailable (``None``), never 0.0."""
        assert _lag_seconds(5, None, datetime(2026, 1, 1, tzinfo=UTC)) is None

    def test_unparseable_last_updated_is_none(self):
        """A timestamp that will not parse yields ``None``, not 0.0."""
        assert _lag_seconds(5, "not-a-timestamp", datetime(2026, 1, 1, tzinfo=UTC)) is (
            None
        )

    def test_clock_skew_clamps_to_zero(self):
        """A position timestamp slightly ahead of ``now`` clamps to 0.0."""
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        ahead = (now + timedelta(seconds=3)).isoformat()
        assert _lag_seconds(5, ahead, now) == 0.0


class TestUnknownStatus:
    def test_returns_unknown_subscription_status(self):
        result = _unknown_status("sub-1", "MyHandler", "stream", "my-stream")
        assert result.name == "sub-1"
        assert result.handler_name == "MyHandler"
        assert result.subscription_type == "stream"
        assert result.stream_category == "my-stream"
        assert result.lag is None
        assert result.status == "unknown"
        assert result.pending == 0
        assert result.dlq_depth == 0


# ---------------------------------------------------------------------------
# Stream category inference
# ---------------------------------------------------------------------------


class TestInferStreamCategory:
    def test_explicit_stream_category_on_handler(self):
        handler = MagicMock()
        handler.__name__ = "TestHandler"
        handler.meta_.stream_category = "explicit-stream"
        handler.meta_.part_of = None
        assert _infer_stream_category(handler) == "explicit-stream"

    def test_infers_from_part_of_aggregate(self):
        handler = MagicMock()
        handler.__name__ = "TestHandler"
        handler.meta_.stream_category = None
        handler.meta_.part_of = MagicMock()
        handler.meta_.part_of.meta_.stream_category = "order"
        assert _infer_stream_category(handler) == "order"

    def test_raises_when_no_meta(self):
        handler = MagicMock(spec=[])
        handler.__name__ = "NoMetaHandler"
        with pytest.raises(ValueError, match="has no meta_ attribute"):
            _infer_stream_category(handler)

    def test_raises_when_no_stream_category(self):
        handler = MagicMock()
        handler.__name__ = "AmbiguousHandler"
        handler.meta_.stream_category = None
        handler.meta_.part_of = None
        with pytest.raises(ValueError, match="Cannot infer stream category"):
            _infer_stream_category(handler)


# ---------------------------------------------------------------------------
# EventStore subscription status collection
# ---------------------------------------------------------------------------


class TestCollectEventStoreStatus:
    def test_computes_lag_correctly(self):
        """When current_position=5 and head=10, lag should be 5."""
        mock_domain = MagicMock()
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store

        # Position stream returns current position
        mock_store._read_last_message.return_value = {"data": {"position": 5}}
        # Head position
        mock_store.stream_head_position.return_value = 10

        handler_cls = MagicMock()
        handler_cls.__name__ = "OrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "OrderHandler"

        result = _collect_event_store_status(
            mock_domain, "order-handler", handler_cls, "order"
        )

        assert result.lag == 5
        assert result.current_position == "5"
        assert result.head_position == "10"
        assert result.status == "lagging"

    def test_lag_seconds_from_last_updated_and_clock(self):
        """A lagging event-store subscription reports seconds behind the clock."""
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        last_updated = (now - timedelta(seconds=30)).isoformat()

        mock_domain = MagicMock()
        mock_domain.clock.now.return_value = now
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store

        mock_store._read_last_message.return_value = {
            "data": {"position": 5},
            "time": last_updated,
        }
        mock_store.stream_head_position.return_value = 10

        handler_cls = MagicMock()
        handler_cls.__name__ = "LaggingHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "LaggingHandler"

        result = _collect_event_store_status(
            mock_domain, "lagging", handler_cls, "order"
        )

        assert result.lag == 5
        assert result.lag_seconds == pytest.approx(30.0)

    def test_lag_seconds_none_without_last_updated(self):
        """No ``last_updated`` reports ``lag_seconds is None``, not 0.0."""
        mock_domain = MagicMock()
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store

        # No "time" key, so last_updated is None even though lag is positive.
        mock_store._read_last_message.return_value = {"data": {"position": 5}}
        mock_store.stream_head_position.return_value = 10

        handler_cls = MagicMock()
        handler_cls.__name__ = "NoTimeHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "NoTimeHandler"

        result = _collect_event_store_status(
            mock_domain, "no-time", handler_cls, "order"
        )

        assert result.lag == 5
        assert result.lag_seconds is None

    def test_lag_zero_when_caught_up(self):
        mock_domain = MagicMock()
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store

        mock_store._read_last_message.return_value = {"data": {"position": 10}}
        mock_store.stream_head_position.return_value = 10

        handler_cls = MagicMock()
        handler_cls.__name__ = "CaughtUpHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "CaughtUpHandler"

        result = _collect_event_store_status(
            mock_domain, "caught-up", handler_cls, "order"
        )

        assert result.lag == 0
        assert result.status == "ok"
        assert result.lag_seconds == 0.0

    def test_unknown_when_empty_stream(self):
        """When head is -1 (no messages), lag should be None."""
        mock_domain = MagicMock()
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store

        mock_store._read_last_message.return_value = None
        mock_store.stream_head_position.return_value = -1

        handler_cls = MagicMock()
        handler_cls.__name__ = "EmptyHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "EmptyHandler"

        result = _collect_event_store_status(
            mock_domain, "empty", handler_cls, "nothing"
        )

        assert result.lag is None
        assert result.status == "unknown"

    def test_graceful_degradation_on_error(self):
        """Returns unknown status when event store query fails."""
        mock_domain = MagicMock()
        mock_domain.event_store.store._read_last_message.side_effect = RuntimeError(
            "event store down"
        )

        handler_cls = MagicMock()
        handler_cls.__name__ = "FailHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "FailHandler"

        result = _collect_event_store_status(
            mock_domain, "fail-sub", handler_cls, "broken"
        )

        assert result.status == "unknown"
        assert result.lag is None

    def test_unknown_when_event_store_not_initialized(self):
        """Returns unknown status when the backing store is None."""
        mock_domain = MagicMock()
        mock_domain.event_store.store = None

        handler_cls = MagicMock()
        handler_cls.__name__ = "UninitHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "UninitHandler"

        result = _collect_event_store_status(
            mock_domain, "uninit-sub", handler_cls, "order"
        )

        assert result.status == "unknown"
        assert result.subscription_type == "event_store"
        assert result.handler_name == "UninitHandler"


# ---------------------------------------------------------------------------
# Stream subscription status collection
# ---------------------------------------------------------------------------


class TestCollectStreamStatus:
    def test_uses_native_lag_when_available(self):
        """Uses Redis 7.0+ native lag field from xinfo_groups."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.handlers.OrderHandler",
                "pending": 2,
                "last-delivered-id": "1234-0",
                "lag": 5,
                "consumers": 1,
            }
        ]

        handler_cls = MagicMock()
        handler_cls.__name__ = "OrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "OrderHandler"

        # Mock broker's _get_field_value to return the correct field
        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_stream_status(
            mock_domain, "order-stream", handler_cls, "order"
        )

        assert result.lag == 5
        assert result.pending == 2
        assert result.consumer_count == 1

    def test_falls_back_to_xrange_when_no_native_lag(self):
        """Falls back to xrange counting when Redis < 7.0."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 50
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.handlers.OrderHandler",
                "pending": 1,
                "last-delivered-id": "1000-0",
                "consumers": 2,
            }
        ]
        # xrange returns 3 messages after last-delivered-id
        mock_redis.xrange.return_value = [
            ("1001-0", {}),
            ("1002-0", {}),
            ("1003-0", {}),
        ]

        handler_cls = MagicMock()
        handler_cls.__name__ = "OrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "OrderHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_stream_status(
            mock_domain, "order-stream", handler_cls, "order"
        )

        assert result.lag == 3
        assert result.pending == 1
        assert result.consumer_count == 2

    def test_unknown_when_broker_not_available(self):
        mock_domain = MagicMock()
        mock_domain.brokers.get.return_value = None

        handler_cls = MagicMock()
        handler_cls.__name__ = "Handler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "Handler"

        result = _collect_stream_status(mock_domain, "no-broker", handler_cls, "test")

        assert result.status == "unknown"

    def test_dlq_depth_queried(self):
        """DLQ depth is read from the :dlq stream."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.side_effect = lambda name: 7 if name.endswith(":dlq") else 100
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.handlers.H",
                "pending": 0,
                "last-delivered-id": "999-0",
                "lag": 0,
                "consumers": 1,
            }
        ]

        handler_cls = MagicMock()
        handler_cls.__name__ = "H"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "H"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_stream_status(
            mock_domain, "h-stream", handler_cls, "my-stream"
        )

        assert result.dlq_depth == 7


# ---------------------------------------------------------------------------
# Outbox processor status collection
# ---------------------------------------------------------------------------


class TestCollectOutboxStatuses:
    def test_returns_empty_when_no_outbox(self):
        mock_domain = MagicMock()
        mock_domain.has_outbox = False

        result = _collect_outbox_statuses(mock_domain)
        assert result == []

    def test_returns_status_per_provider(self):
        mock_domain = MagicMock()
        mock_domain.has_outbox = True
        mock_domain.config = {"outbox": {"broker": "default"}}
        mock_domain.providers = {"default": MagicMock(managed=True)}

        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {
            "pending": 3,
            "processing": 1,
            "failed": 2,
            "abandoned": 0,
        }
        mock_domain._get_outbox_repo.return_value = mock_outbox

        result = _collect_outbox_statuses(mock_domain)
        assert len(result) == 1

        status = result[0]
        assert status.handler_name == "OutboxProcessor"
        assert status.subscription_type == "outbox"
        assert status.lag == 4  # pending + processing
        assert status.pending == 3
        assert status.dlq_depth == 2  # failed + abandoned
        assert status.status == "lagging"

    def test_ok_when_no_pending(self):
        mock_domain = MagicMock()
        mock_domain.has_outbox = True
        mock_domain.config = {"outbox": {"broker": "default"}}
        mock_domain.providers = {"default": MagicMock(managed=True)}

        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
            "abandoned": 0,
        }
        mock_domain._get_outbox_repo.return_value = mock_outbox

        result = _collect_outbox_statuses(mock_domain)
        assert len(result) == 1
        assert result[0].status == "ok"
        assert result[0].lag == 0

    def test_graceful_degradation_on_error(self):
        mock_domain = MagicMock()
        mock_domain.has_outbox = True
        mock_domain.config = {"outbox": {"broker": "default"}}
        mock_domain.providers = {"default": MagicMock(managed=True)}
        mock_domain.domain_context.return_value.__enter__ = MagicMock(
            side_effect=RuntimeError("db down")
        )

        result = _collect_outbox_statuses(mock_domain)
        assert len(result) == 1
        assert result[0].status == "unknown"


# ---------------------------------------------------------------------------
# Public collection function
# ---------------------------------------------------------------------------


class TestCollectSubscriptionStatuses:
    def test_empty_domain_returns_empty_list(self):
        """A domain with no handlers returns an empty list."""
        mock_domain = MagicMock()
        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        result = collect_subscription_statuses(mock_domain)
        assert result == []

    def test_discovers_event_handler(self):
        """Collects status for a registered event handler."""
        mock_domain = MagicMock()

        handler_cls = MagicMock()
        handler_cls.__name__ = "OrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "OrderHandler"
        handler_cls.meta_.stream_category = "order"
        handler_cls.meta_.part_of = None

        record = MagicMock()
        record.cls = handler_cls

        mock_domain.registry.event_handlers = {"order-handler": record}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        # Mock ConfigResolver to return event_store type
        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.EVENT_STORE

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            # Mock _collect_event_store_status to avoid infrastructure
            with patch(
                "protean.server.subscription_status._collect_event_store_status"
            ) as mock_collect:
                mock_collect.return_value = SubscriptionStatus(
                    name="order-handler",
                    handler_name="OrderHandler",
                    subscription_type="event_store",
                    stream_category="order",
                    lag=0,
                    pending=0,
                    current_position="10",
                    head_position="10",
                    status="ok",
                    consumer_count=0,
                    dlq_depth=0,
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        assert result[0].handler_name == "OrderHandler"
        assert result[0].status == "ok"

    def test_discovers_command_handler_dispatcher(self):
        """Command handlers are grouped by stream into a single dispatcher subscription."""
        mock_domain = MagicMock()

        handler_cls = MagicMock()
        handler_cls.__name__ = "PlaceOrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "PlaceOrderHandler"
        handler_cls.meta_.stream_category = "order"
        handler_cls.meta_.part_of = None

        record = MagicMock()
        record.cls = handler_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {"place-order": record}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.STREAM

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_stream_status"
            ) as mock_collect:
                mock_collect.return_value = SubscriptionStatus(
                    name="commands:order",
                    handler_name="PlaceOrderHandler",
                    subscription_type="stream",
                    stream_category="order",
                    lag=0,
                    pending=0,
                    current_position="0-0",
                    head_position="100",
                    status="ok",
                    consumer_count=1,
                    dlq_depth=0,
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        assert result[0].name == "commands:order"

        # Verify the dispatcher fqn was used as consumer group name
        mock_collect.assert_called_once()
        call_kwargs = mock_collect.call_args
        assert (
            call_kwargs.kwargs["consumer_group_name"]
            == "protean.server.engine.Commands:order"
        )

    def test_discovers_projectors_across_streams(self):
        """A projector with two stream_categories produces two statuses."""
        mock_domain = MagicMock()

        projector_cls = MagicMock()
        projector_cls.__name__ = "OrderSummary"
        projector_cls.__module__ = "tests.projectors"
        projector_cls.__qualname__ = "OrderSummary"
        projector_cls.meta_.stream_categories = ["order", "payment"]

        record = MagicMock()
        record.cls = projector_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {"order-summary": record}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.EVENT_STORE

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_event_store_status"
            ) as mock_collect:
                mock_collect.return_value = _unknown_status(
                    "stub", "OrderSummary", "event_store", "order"
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 2
        # Called once per stream category
        assert mock_collect.call_count == 2

    def test_discovers_event_handler_stream_type(self):
        """Event handler resolved to STREAM type calls _collect_stream_status."""
        mock_domain = MagicMock()

        handler_cls = MagicMock()
        handler_cls.__name__ = "OrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "OrderHandler"
        handler_cls.meta_.stream_category = "order"
        handler_cls.meta_.part_of = None

        record = MagicMock()
        record.cls = handler_cls

        mock_domain.registry.event_handlers = {"order-handler": record}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.STREAM

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_stream_status"
            ) as mock_collect:
                mock_collect.return_value = _unknown_status(
                    "order-handler", "OrderHandler", "stream", "order"
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        mock_collect.assert_called_once()

    def test_skips_handler_with_no_stream_category(self):
        """Handlers that raise ValueError in _infer_stream_category are skipped."""
        mock_domain = MagicMock()

        handler_cls = MagicMock()
        handler_cls.__name__ = "BrokenHandler"
        handler_cls.meta_.stream_category = None
        handler_cls.meta_.part_of = None

        record = MagicMock()
        record.cls = handler_cls

        # Also a command handler with broken stream category
        cmd_handler_cls = MagicMock()
        cmd_handler_cls.__name__ = "BrokenCmd"
        cmd_handler_cls.meta_.stream_category = None
        cmd_handler_cls.meta_.part_of = None

        cmd_record = MagicMock()
        cmd_record.cls = cmd_handler_cls

        mock_domain.registry.event_handlers = {"broken-handler": record}
        mock_domain.registry.command_handlers = {"broken-cmd": cmd_record}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        with patch("protean.server.subscription_status.ConfigResolver"):
            result = collect_subscription_statuses(mock_domain)

        assert result == []

    def test_discovers_command_handler_event_store_type(self):
        """Command handler resolved to EVENT_STORE type calls _collect_event_store_status."""
        mock_domain = MagicMock()

        handler_cls = MagicMock()
        handler_cls.__name__ = "PlaceOrderHandler"
        handler_cls.__module__ = "tests.handlers"
        handler_cls.__qualname__ = "PlaceOrderHandler"
        handler_cls.meta_.stream_category = "order"
        handler_cls.meta_.part_of = None

        record = MagicMock()
        record.cls = handler_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {"place-order": record}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.EVENT_STORE

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_event_store_status"
            ) as mock_collect:
                mock_collect.return_value = _unknown_status(
                    "commands:order", "PlaceOrderHandler", "event_store", "order"
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        mock_collect.assert_called_once()
        call_kwargs = mock_collect.call_args
        assert (
            call_kwargs.kwargs["subscriber_name"]
            == "protean.server.engine.Commands:order"
        )

    def test_discovers_projector_stream_type(self):
        """Projector resolved to STREAM type calls _collect_stream_status."""
        mock_domain = MagicMock()

        projector_cls = MagicMock()
        projector_cls.__name__ = "OrderSummary"
        projector_cls.__module__ = "tests.projectors"
        projector_cls.__qualname__ = "OrderSummary"
        projector_cls.meta_.stream_categories = ["order"]

        record = MagicMock()
        record.cls = projector_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {"order-summary": record}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.STREAM

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_stream_status"
            ) as mock_collect:
                mock_collect.return_value = _unknown_status(
                    "stub", "OrderSummary", "stream", "order"
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        mock_collect.assert_called_once()

    def test_discovers_process_managers(self):
        """Process managers produce one status per stream category."""
        mock_domain = MagicMock()

        pm_cls = MagicMock()
        pm_cls.__name__ = "PaymentFlow"
        pm_cls.__module__ = "tests.pm"
        pm_cls.__qualname__ = "PaymentFlow"
        pm_cls.meta_.stream_categories = ["order", "payment"]

        record = MagicMock()
        record.cls = pm_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {"payment-flow": record}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.EVENT_STORE

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_event_store_status"
            ) as mock_collect:
                mock_collect.return_value = _unknown_status(
                    "stub", "PaymentFlow", "event_store", "order"
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 2
        assert mock_collect.call_count == 2

    def test_discovers_process_managers_stream_type(self):
        """Process managers with STREAM type call _collect_stream_status."""
        mock_domain = MagicMock()

        pm_cls = MagicMock()
        pm_cls.__name__ = "PaymentFlow"
        pm_cls.__module__ = "tests.pm"
        pm_cls.__qualname__ = "PaymentFlow"
        pm_cls.meta_.stream_categories = ["order"]

        record = MagicMock()
        record.cls = pm_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {"payment-flow": record}
        mock_domain.registry.subscribers = {}
        mock_domain.has_outbox = False

        from protean.server.subscription.profiles import SubscriptionType

        mock_config = MagicMock()
        mock_config.subscription_type = SubscriptionType.STREAM

        with patch("protean.server.subscription_status.ConfigResolver") as MockResolver:
            resolver_instance = MockResolver.return_value
            resolver_instance.resolve.return_value = mock_config

            with patch(
                "protean.server.subscription_status._collect_stream_status"
            ) as mock_collect:
                mock_collect.return_value = _unknown_status(
                    "stub", "PaymentFlow", "stream", "order"
                )

                result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        mock_collect.assert_called_once()

    def test_discovers_broker_subscribers(self):
        """Broker subscribers call _collect_broker_status."""
        mock_domain = MagicMock()

        subscriber_cls = MagicMock()
        subscriber_cls.__name__ = "ExternalHandler"
        subscriber_cls.__module__ = "tests.subscribers"
        subscriber_cls.__qualname__ = "ExternalHandler"
        subscriber_cls.meta_.broker = "default"
        subscriber_cls.meta_.stream = "external-events"

        record = MagicMock()
        record.cls = subscriber_cls

        mock_domain.registry.event_handlers = {}
        mock_domain.registry.command_handlers = {}
        mock_domain.registry.projectors = {}
        mock_domain.registry.process_managers = {}
        mock_domain.registry.subscribers = {"ext-handler": record}
        mock_domain.has_outbox = False

        with (
            patch("protean.server.subscription_status.ConfigResolver"),
            patch(
                "protean.server.subscription_status._collect_broker_status"
            ) as mock_collect,
        ):
            mock_collect.return_value = _unknown_status(
                "ext-handler", "ExternalHandler", "broker", "external-events"
            )

            result = collect_subscription_statuses(mock_domain)

        assert len(result) == 1
        mock_collect.assert_called_once_with(
            mock_domain, "ext-handler", subscriber_cls, "external-events", "default"
        )


# ---------------------------------------------------------------------------
# Broker subscription status collection
# ---------------------------------------------------------------------------


class TestCollectBrokerStatus:
    def test_redis_broker_with_native_lag(self):
        """Broker with redis_instance uses Redis introspection."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 200
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.subscribers.ExternalHandler",
                "pending": 5,
                "last-delivered-id": "500-0",
                "lag": 10,
                "consumers": 3,
            }
        ]

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.subscription_type == "broker"
        assert result.lag == 10
        assert result.pending == 5
        assert result.consumer_count == 3

    def test_redis_broker_xrange_fallback(self):
        """Broker falls back to xrange when no native lag field."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 50
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.subscribers.ExternalHandler",
                "pending": 2,
                "last-delivered-id": "100-0",
                "consumers": 1,
            }
        ]
        mock_redis.xrange.return_value = [("101-0", {}), ("102-0", {})]

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.lag == 2
        assert result.pending == 2

    def test_non_redis_broker_uses_info_api(self):
        """Broker without redis_instance uses info() API."""
        mock_domain = MagicMock()
        mock_broker = MagicMock(spec=["info", "get"])
        # No redis_instance attribute (spec controls which attributes exist)
        mock_domain.brokers.get.return_value = mock_broker

        mock_broker.info.return_value = {
            "consumer_groups": {
                "tests.subscribers.ExternalHandler": {
                    "pending": 7,
                    "consumer_count": 2,
                }
            }
        }

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.subscription_type == "broker"
        assert result.lag == 7
        assert result.pending == 7
        assert result.consumer_count == 2
        assert result.status == "lagging"

    def test_non_redis_broker_ok_when_no_pending(self):
        """Non-Redis broker returns ok when no pending."""
        mock_domain = MagicMock()
        mock_broker = MagicMock(spec=["info", "get"])
        mock_domain.brokers.get.return_value = mock_broker

        mock_broker.info.return_value = {
            "consumer_groups": {
                "tests.subscribers.ExternalHandler": {
                    "pending": 0,
                    "consumer_count": 1,
                }
            }
        }

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.status == "ok"

    def test_unknown_when_broker_is_none(self):
        """Returns unknown when broker is not configured."""
        mock_domain = MagicMock()
        mock_domain.brokers.get.return_value = None

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "ext-events", "default"
        )

        assert result.status == "unknown"

    def test_graceful_degradation_on_error(self):
        """Returns unknown when broker query raises."""
        mock_domain = MagicMock()
        mock_domain.brokers.get.side_effect = RuntimeError("broker down")

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "ext-events", "default"
        )

        assert result.status == "unknown"

    def test_redis_broker_xlen_exception(self):
        """When xlen raises on Redis broker, stream_length defaults to 0."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.side_effect = Exception("stream gone")
        mock_redis.xinfo_groups.return_value = []

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.head_position == "0"

    def test_redis_broker_non_dict_group_entries(self):
        """Non-dict entries in xinfo_groups are skipped for broker."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [
            "not-a-dict",
            42,
            {
                "name": "tests.subscribers.ExternalHandler",
                "pending": 0,
                "last-delivered-id": "99-0",
                "lag": 0,
                "consumers": 1,
            },
        ]

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.lag == 0
        assert result.status == "ok"

    def test_redis_broker_xinfo_groups_exception(self):
        """When xinfo_groups raises, group data is skipped."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.side_effect = Exception("no groups")

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.lag is None
        assert result.pending == 0

    def test_redis_broker_group_name_mismatch(self):
        """Broker skips groups with non-matching names."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "other-group",
                "pending": 99,
                "last-delivered-id": "10-0",
                "lag": 50,
                "consumers": 5,
            },
            {
                "name": "tests.subscribers.ExternalHandler",
                "pending": 2,
                "last-delivered-id": "98-0",
                "lag": 2,
                "consumers": 1,
            },
        ]

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        # Should pick up second group's values
        assert result.lag == 2
        assert result.pending == 2
        assert result.consumer_count == 1

    def test_redis_broker_xrange_exception_leaves_lag_unknown(self):
        """When xrange fails, lag stays unknown rather than becoming pending.

        `lag = pending` reads like a conservative lower bound, but with nothing
        pending it is `lag: 0`, which classifies as `ok` and reports a
        subscription as caught up when its lag was never read (#1288).
        """
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()

        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.subscribers.ExternalHandler",
                "pending": 3,
                "last-delivered-id": "50-0",
                "consumers": 1,
            }
        ]
        mock_redis.xrange.side_effect = Exception("xrange failed")

        handler_cls = MagicMock()
        handler_cls.__name__ = "ExternalHandler"
        handler_cls.__module__ = "tests.subscribers"
        handler_cls.__qualname__ = "ExternalHandler"

        def _get_field_value(d, key, convert_to_int=False):
            val = d.get(key)
            if convert_to_int and val is not None:
                return int(val)
            return val

        mock_broker._get_field_value.side_effect = _get_field_value

        result = _collect_broker_status(
            mock_domain, "ext-handler", handler_cls, "external-events", "default"
        )

        assert result.lag is None
        assert result.status == "unknown"
        assert result.pending == 3


# ---------------------------------------------------------------------------
# Stream status edge cases (error paths)
# ---------------------------------------------------------------------------


class TestStreamStatusEdgeCases:
    def _make_mock_domain_with_redis(self):
        """Create a mock domain with a redis broker."""
        mock_domain = MagicMock()
        mock_broker = MagicMock()
        mock_redis = MagicMock()
        mock_domain.brokers.get.return_value = mock_broker
        mock_broker.redis_instance = mock_redis
        return mock_domain, mock_broker, mock_redis

    def _make_handler(self, name="TestHandler"):
        handler = MagicMock()
        handler.__name__ = name
        handler.__module__ = "tests.handlers"
        handler.__qualname__ = name
        return handler

    def _field_getter(self, d, key, convert_to_int=False):
        val = d.get(key)
        if convert_to_int and val is not None:
            return int(val)
        return val

    def test_xlen_exception_sets_stream_length_to_zero(self):
        """When xlen raises, stream_length defaults to 0."""
        mock_domain, mock_broker, mock_redis = self._make_mock_domain_with_redis()
        handler_cls = self._make_handler()

        mock_redis.xlen.side_effect = Exception("stream gone")
        mock_redis.xinfo_groups.return_value = []

        mock_broker._get_field_value.side_effect = self._field_getter

        result = _collect_stream_status(
            mock_domain, "sub", handler_cls, "broken-stream"
        )

        assert result.head_position == "0"

    def test_xinfo_groups_exception_skips_group_data(self):
        """When xinfo_groups raises, no group info is available."""
        mock_domain, mock_broker, mock_redis = self._make_mock_domain_with_redis()
        handler_cls = self._make_handler()

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.side_effect = Exception("no groups")

        mock_broker._get_field_value.side_effect = self._field_getter

        result = _collect_stream_status(mock_domain, "sub", handler_cls, "my-stream")

        assert result.pending == 0
        assert (
            result.lag is None
        )  # No group info, no last_delivered_id → lag stays None

    def test_xrange_exception_leaves_lag_unknown(self):
        """An unreadable lag is null, not the pending count.

        Falling back to `pending` reported `lag: 0, status: "ok"` whenever
        nothing happened to be pending, so a subscription whose lag could not
        be read at all looked healthy (#1288).
        """
        mock_domain, mock_broker, mock_redis = self._make_mock_domain_with_redis()
        handler_cls = self._make_handler()

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.handlers.TestHandler",
                "pending": 4,
                "last-delivered-id": "50-0",
                "consumers": 1,
            }
        ]
        mock_redis.xrange.side_effect = Exception("xrange failed")

        mock_broker._get_field_value.side_effect = self._field_getter

        result = _collect_stream_status(mock_domain, "sub", handler_cls, "my-stream")

        assert result.lag is None
        assert result.status == "unknown"
        # The pending count is still reported; it just is not passed off as lag.
        assert result.pending == 4

    def test_dlq_xlen_exception_sets_dlq_to_zero(self):
        """When DLQ xlen fails, dlq_depth stays 0."""
        mock_domain, mock_broker, mock_redis = self._make_mock_domain_with_redis()
        handler_cls = self._make_handler()

        def xlen_side_effect(name):
            if ":dlq" in name:
                raise Exception("dlq gone")
            return 100

        mock_redis.xlen.side_effect = xlen_side_effect
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "tests.handlers.TestHandler",
                "pending": 0,
                "last-delivered-id": "99-0",
                "lag": 0,
                "consumers": 1,
            }
        ]

        mock_broker._get_field_value.side_effect = self._field_getter

        result = _collect_stream_status(mock_domain, "sub", handler_cls, "my-stream")

        assert result.dlq_depth == 0

    def test_top_level_exception_returns_unknown(self):
        """When the outer try/except catches, returns unknown."""
        mock_domain = MagicMock()
        mock_domain.domain_context.return_value.__enter__ = MagicMock(
            side_effect=RuntimeError("context failed")
        )

        handler_cls = self._make_handler()

        result = _collect_stream_status(mock_domain, "sub", handler_cls, "my-stream")

        assert result.status == "unknown"

    def test_group_name_mismatch_continues_loop(self):
        """When consumer group name doesn't match, continues to next entry."""
        mock_domain, mock_broker, mock_redis = self._make_mock_domain_with_redis()
        handler_cls = self._make_handler()

        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [
            {
                "name": "other-consumer-group",
                "pending": 10,
                "last-delivered-id": "50-0",
                "lag": 20,
                "consumers": 3,
            },
            {
                "name": "tests.handlers.TestHandler",
                "pending": 1,
                "last-delivered-id": "99-0",
                "lag": 1,
                "consumers": 1,
            },
        ]

        mock_broker._get_field_value.side_effect = self._field_getter

        result = _collect_stream_status(mock_domain, "sub", handler_cls, "my-stream")

        # Should use the second group's values, not the first
        assert result.lag == 1
        assert result.pending == 1
        assert result.consumer_count == 1

    def test_non_dict_group_entries_are_skipped(self):
        """Non-dict entries in xinfo_groups are skipped."""
        mock_domain, mock_broker, mock_redis = self._make_mock_domain_with_redis()
        handler_cls = self._make_handler()

        mock_redis.xlen.return_value = 50
        mock_redis.xinfo_groups.return_value = [
            "not-a-dict",
            42,
            {
                "name": "tests.handlers.TestHandler",
                "pending": 0,
                "last-delivered-id": "49-0",
                "lag": 0,
                "consumers": 1,
            },
        ]

        mock_broker._get_field_value.side_effect = self._field_getter

        result = _collect_stream_status(mock_domain, "sub", handler_cls, "my-stream")

        # Should still find the correct group despite non-dict entries
        assert result.lag == 0
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# Infer stream category edge cases
# ---------------------------------------------------------------------------


class TestInferStreamCategoryEdgeCases:
    def test_part_of_with_no_aggregate_meta(self):
        """When part_of has no meta_, falls through to ValueError."""
        handler = MagicMock()
        handler.__name__ = "WeirdHandler"
        handler.meta_.stream_category = None
        handler.meta_.part_of = MagicMock(spec=[])  # no meta_ attribute

        with pytest.raises(ValueError, match="Cannot infer"):
            _infer_stream_category(handler)

    def test_part_of_with_no_aggregate_stream_category(self):
        """When aggregate meta has no stream_category, falls through."""
        handler = MagicMock()
        handler.__name__ = "WeirdHandler"
        handler.meta_.stream_category = None
        handler.meta_.part_of = MagicMock()
        handler.meta_.part_of.meta_.stream_category = None

        with pytest.raises(ValueError, match="Cannot infer"):
            _infer_stream_category(handler)


# ---------------------------------------------------------------------------
# Checkpoint stream carried on the status
# ---------------------------------------------------------------------------


class TestPositionStreamField:
    def test_event_store_status_carries_its_checkpoint_stream(self):
        """The event-store status names the ``position-{fqn}-{category}`` stream a
        reset writes to; other subscription types leave it ``None``."""
        mock_domain = MagicMock()
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store
        mock_domain.clock.now.return_value = datetime(2026, 1, 1, tzinfo=UTC)
        mock_store._read_last_message.return_value = {"data": {"position": 5}}
        mock_store.stream_head_position.return_value = 10

        handler = MagicMock()
        handler.__name__ = "OrderHandler"

        result = _collect_event_store_status(
            mock_domain,
            "order-handler",
            handler,
            "order",
            subscriber_name="my.OrderHandler",
        )

        assert result.position_stream == "position-my.OrderHandler-order"

    def test_position_stream_falls_back_to_handler_fqn(self):
        """With no explicit subscriber_name, the checkpoint stream is built from
        the handler's fqn, matching what an event handler / projector uses."""
        from protean.utils import fqn

        mock_domain = MagicMock()
        mock_store = MagicMock()
        mock_domain.event_store.store = mock_store
        mock_domain.clock.now.return_value = datetime(2026, 1, 1, tzinfo=UTC)
        mock_store._read_last_message.return_value = {"data": {"position": 1}}
        mock_store.stream_head_position.return_value = 5

        class OrderHandler:
            pass

        result = _collect_event_store_status(mock_domain, "n", OrderHandler, "order")

        assert result.position_stream == f"position-{fqn(OrderHandler)}-order"

    def test_reset_targets_the_stream_the_subscription_reads(self, test_domain):
        """The stream a reset writes to (status.position_stream) is exactly the
        stream a live EventStoreSubscription loads its checkpoint from. Binds the
        two independent ``position-...`` derivations so a drift cannot send the
        reset to a dead stream the engine never reads."""
        from protean.server.engine import Engine
        from protean.server.subscription.event_store_subscription import (
            EventStoreSubscription,
        )

        class OrderHandler:
            pass

        with test_domain.domain_context():
            engine = Engine(test_domain, test_mode=True)
            subscription = EventStoreSubscription(engine, "order", OrderHandler)

        status = _collect_event_store_status(
            test_domain, "order-handler", OrderHandler, "order"
        )

        assert status.position_stream == subscription.subscriber_stream_name

    def test_unknown_status_has_no_checkpoint_stream(self):
        assert _unknown_status("n", "H", "event_store", "order").position_stream is None


# ---------------------------------------------------------------------------
# reset_checkpoint_to_head
# ---------------------------------------------------------------------------


def _es_status(
    *,
    name: str = "sub",
    handler_name: str = "Handler",
    subscription_type: str = "event_store",
    stream_category: str = "order",
    current_position: str | None = "999",
    head_position: str | None = "0",
    position_stream: str | None = "position-Handler-order",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=name,
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=0,
        pending=0,
        current_position=current_position,
        head_position=head_position,
        status="ok",
        consumer_count=0,
        dlq_depth=0,
        position_stream=position_stream,
    )


def _seed_checkpoint(store, position_stream: str, position: int) -> None:
    """Write a ``Read`` position record, the shape a live subscription writes."""
    store._write(position_stream, "Read", {"position": position})


class TestResetCheckpointToHead:
    def test_writes_status_head_to_checkpoint_stream(self, test_domain):
        """The reset writes the head recorded on the status (from verification),
        readable back from the checkpoint stream, in the same ``Read`` record shape
        the runtime writes. It uses that recorded head, not a fresh store read, so
        the live store head deliberately differs here to pin which one is used."""
        from protean.server.subscription_status import reset_checkpoint_to_head

        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Live store head for `order` is 2; the status carries head 7 from
            # verification. The reset must write 7, not the live 2.
            store._write("order-1", "Placed", {"n": 1})
            store._write("order-1", "Placed", {"n": 2})
            assert store.stream_head_position("order") == 2
            # A stale checkpoint sitting well past the head.
            _seed_checkpoint(store, "position-Handler-order", 99)

        status = _es_status(
            stream_category="order",
            current_position="99",
            head_position="7",
            position_stream="position-Handler-order",
        )
        new_position = reset_checkpoint_to_head(test_domain, status)

        assert new_position == 7
        with test_domain.domain_context():
            last = store._read_last_message("position-Handler-order")
        assert last is not None
        assert last["data"]["position"] == 7
        # Same record type the runtime EventStoreSubscription.write_position writes.
        assert last["type"] == "Read"

    def test_reset_then_verify_reads_consistent(self, test_domain):
        """Criterion 1 round-trip: after a reset, the subscription verifies as
        consistent against the same head."""
        from protean.cli.recover import _verdict
        from protean.server.subscription_status import reset_checkpoint_to_head

        store = test_domain.event_store.store
        with test_domain.domain_context():
            store._write("order-1", "Placed", {"n": 1})
            head = store.stream_head_position("order")
            _seed_checkpoint(store, "position-RT-order", head + 5)

        stale = _es_status(
            stream_category="order",
            current_position=str(head + 5),
            head_position=str(head),
            position_stream="position-RT-order",
        )
        assert _verdict(stale) == "beyond_head"

        reset_checkpoint_to_head(test_domain, stale)

        with test_domain.domain_context():
            written = store._read_last_message("position-RT-order")["data"]["position"]
        verified = _es_status(
            stream_category="order",
            current_position=str(written),
            head_position=str(head),
            position_stream="position-RT-order",
        )
        assert _verdict(verified) == "consistent"

    def test_empty_stream_resets_to_minus_one(self, test_domain):
        """A restored stream with no events has head ``-1``; the reset writes that,
        which sends the subscription back to the start of the stream."""
        from protean.server.subscription_status import reset_checkpoint_to_head

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = store.stream_head_position("empty")
        assert head == -1

        status = _es_status(
            stream_category="empty",
            current_position="4",
            head_position="-1",
            position_stream="position-Handler-empty",
        )
        new_position = reset_checkpoint_to_head(test_domain, status)

        assert new_position == -1
        with test_domain.domain_context():
            last = store._read_last_message("position-Handler-empty")
        assert last is not None
        assert last["data"]["position"] == -1

    def test_raises_for_non_event_store_status(self, test_domain):
        from protean.server.subscription_status import reset_checkpoint_to_head

        status = _es_status(subscription_type="broker")
        with pytest.raises(ValueError, match="not an event-store"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_checkpoint_stream_missing(self, test_domain):
        from protean.server.subscription_status import reset_checkpoint_to_head

        status = _es_status(position_stream=None)
        with pytest.raises(ValueError, match="no checkpoint stream"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_head_position_unknown(self, test_domain):
        from protean.server.subscription_status import reset_checkpoint_to_head

        status = _es_status(head_position=None)
        with pytest.raises(ValueError, match="stream head is unknown"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_head_position_not_numeric(self, test_domain):
        from protean.server.subscription_status import reset_checkpoint_to_head

        status = _es_status(head_position="abc")
        with pytest.raises(ValueError, match="not a number"):
            reset_checkpoint_to_head(test_domain, status)

    def test_raises_when_store_not_configured(self):
        from protean.server.subscription_status import reset_checkpoint_to_head

        mock_domain = MagicMock()
        mock_domain.event_store.store = None

        status = _es_status()
        with pytest.raises(ValueError, match="no.*event store"):
            reset_checkpoint_to_head(mock_domain, status)


class TestPerformResetsScope:
    """End-to-end scope check on real infrastructure: a reset run touches only
    the beyond-head checkpoints and leaves at-or-below-head and unknown ones
    alone."""

    def test_only_beyond_head_checkpoint_is_modified(self, test_domain):
        from protean.cli.recover import _perform_resets

        store = test_domain.event_store.store
        with test_domain.domain_context():
            store._write("order-1", "Placed", {"n": 1})
            store._write("payment-1", "Paid", {"n": 1})
            order_head = store.stream_head_position("order")
            payment_head = store.stream_head_position("payment")

            # A healthy checkpoint sitting exactly at head, an unknown one, and a
            # stale one pointing past head.
            _seed_checkpoint(store, "position-Healthy-payment", payment_head)
            _seed_checkpoint(store, "position-Unknown-order", 3)
            _seed_checkpoint(store, "position-Bad-order", order_head + 5)
            healthy_before = store._read_last_message("position-Healthy-payment")
            unknown_before = store._read_last_message("position-Unknown-order")

        bad = _es_status(
            name="bad",
            handler_name="Bad",
            stream_category="order",
            current_position=str(order_head + 5),
            head_position=str(order_head),
            position_stream="position-Bad-order",
        )
        healthy = _es_status(
            name="healthy",
            handler_name="Healthy",
            stream_category="payment",
            current_position=str(payment_head),
            head_position=str(payment_head),
            position_stream="position-Healthy-payment",
        )
        # An unknown row: its positions could not be parsed, so it must be skipped.
        unknown = _es_status(
            name="unknown",
            handler_name="Unknown",
            stream_category="order",
            current_position=None,
            head_position=None,
            position_stream="position-Unknown-order",
        )

        resets, failures = _perform_resets(
            test_domain,
            [bad, healthy, unknown],
            ["beyond_head", "consistent", "unknown"],
        )

        assert failures == []
        assert len(resets) == 1
        assert resets[0]["name"] == "bad"
        assert resets[0]["previous_position"] == str(order_head + 5)
        assert resets[0]["new_position"] == str(order_head)

        with test_domain.domain_context():
            bad_after = store._read_last_message("position-Bad-order")
            healthy_after = store._read_last_message("position-Healthy-payment")
            unknown_after = store._read_last_message("position-Unknown-order")

        # The beyond-head checkpoint advanced to head.
        assert bad_after["data"]["position"] == order_head
        # The healthy and unknown checkpoints got no new record: same
        # global_position (a stray append would raise it), same value.
        assert healthy_after["global_position"] == healthy_before["global_position"]
        assert healthy_after["data"]["position"] == payment_head
        assert unknown_after["global_position"] == unknown_before["global_position"]
        assert unknown_after["data"]["position"] == 3


# ---------------------------------------------------------------------------
# Recovery-tracking checkpoints
# ---------------------------------------------------------------------------


def _rec_status(
    *,
    name: str = "sub",
    handler_name: str = "Handler",
    subscription_type: str = "event_store",
    stream_category: str = "order",
    head_position: str | None = "2",
    recovery_checkpoint_stream: str | None = "recovery-checkpoint-Handler-order",
    failed_positions_stream: str | None = "failed-Handler-order",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=name,
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=0,
        pending=0,
        current_position=head_position,
        head_position=head_position,
        status="ok",
        consumer_count=0,
        dlq_depth=0,
        recovery_checkpoint_stream=recovery_checkpoint_stream,
        failed_positions_stream=failed_positions_stream,
    )


def _seed_recovery_checkpoint(
    store, recovery_stream: str, watermark: int, unresolved: dict, category="order"
) -> None:
    """Write a ``Checkpoint`` record, the shape a live subscription writes."""
    store._write(
        recovery_stream,
        "Checkpoint",
        {"watermark": watermark, "unresolved": unresolved},
        metadata={
            "headers": {
                "id": str(uuid4()),
                "type": "Checkpoint",
                "time": "2026-01-01T00:00:00+00:00",
                "stream": recovery_stream,
            },
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": category,
            },
        },
    )


def _seed_failed_record(
    store,
    failed_stream: str,
    record_type: str,
    position: int,
    category="order",
    stream_name=None,
    stream_position=None,
) -> None:
    """Write a ``Failed``/``Resolved``/``Exhausted`` record to the failed stream.

    ``stream_name``/``stream_position`` default to ``None`` so the recovery re-read
    falls back to the category stream at ``position``; pass a specific stream to
    exercise the specific-stream re-read path.
    """
    store._write(
        failed_stream,
        record_type,
        {
            "position": position,
            "message_type": "Placed",
            "message_id": "abc",
            "retry_count": 1,
            "stream_name": stream_name,
            "stream_position": stream_position,
        },
        metadata={
            "headers": {
                "id": str(uuid4()),
                "type": record_type,
                "time": "2026-01-01T00:00:00+00:00",
                "stream": failed_stream,
            },
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": category,
            },
        },
    )


def _seed_event(
    store, stream_name: str, event_type: str, data: dict, category="order"
) -> None:
    """Write a domain event to a specific stream, with the metadata a real event
    carries so ``store.read`` can deserialize it back (the recovery re-read does).
    """
    store._write(
        stream_name,
        event_type,
        data,
        metadata={
            "headers": {
                "id": str(uuid4()),
                "type": event_type,
                "time": "2026-01-01T00:00:00+00:00",
                "stream": stream_name,
            },
            "domain": {
                "kind": MessageType.EVENT.value,
                "origin_stream": category,
            },
        },
    )


class TestReconstructUnresolved:
    """The shared reconstruction both the runtime rebuild and ``protean recover``
    call: checkpoint snapshot merged with failed-stream records after the
    watermark."""

    def test_snapshot_only(self, test_domain):
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": "order-9",
                        "stream_position": 0,
                    },
                },
            )
            unresolved, watermark, _read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        assert set(unresolved) == {5}
        assert watermark == 0

    def test_failed_stream_after_watermark_is_merged(self, test_domain):
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Snapshot at watermark 0 with one position; the failed stream adds a
            # second and a terminal record retires a third.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "3": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "8": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            _seed_failed_record(store, "failed-Handler-order", "Failed", 9)
            _seed_failed_record(store, "failed-Handler-order", "Resolved", 8)

            unresolved, watermark, _read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # 3 stays (snapshot), 9 added (Failed), 8 removed (Resolved). Watermark
        # advances past the two failed-stream records read (positions 0, 1 -> 2).
        assert set(unresolved) == {3, 9}
        assert watermark == 2

    def test_no_checkpoint_reads_failed_stream_from_zero(self, test_domain):
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            _seed_failed_record(store, "failed-Handler-order", "Failed", 4)
            unresolved, watermark, _read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        assert set(unresolved) == {4}
        assert watermark == 1

    def test_pages_through_the_whole_stream(self, test_domain):
        """The failed stream is paged in full, not capped: a record past the first
        page is still merged, so a long failure history is not silently truncated.
        """
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            for pos in (4, 5, 6, 7, 8):
                _seed_failed_record(store, "failed-Handler-order", "Failed", pos)
            # A tiny page size forces several pages; every record must still merge.
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
                page_size=2,
            )

        assert set(unresolved) == {4, 5, 6, 7, 8}
        assert records_read == 5
        # Watermark advances past the last record (per-stream positions 0..4 -> 5).
        assert watermark == 5

    def test_stale_high_watermark_keeps_snapshot_and_does_not_resurrect(
        self, test_domain
    ):
        """A restore can leave the checkpoint watermark ahead of the failed stream.
        Reconstruction is best-effort: it trusts the snapshot and reads only from
        the stored watermark, so it does not re-read a surviving old failed record
        below the watermark. That old record's terminal (Resolved/Exhausted) row
        may have been truncated, so re-reading it would resurrect an already-
        resolved position. Here a resolved position (5, whose Resolved was rolled
        back) stays out of the set and the snapshot is returned unchanged."""
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            # A surviving old Failed(5) row at per-stream position 0. Its Resolved
            # row was rolled back by the restore, so it is not in the stream.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 5)
            # The checkpoint watermark (10) is past that tail; its snapshot excludes
            # 5 (it was resolved before the restore).
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=10,
                unresolved={
                    "99": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # 5 is NOT resurrected (the old survivor below the watermark is not
        # re-read); the snapshot (99) is returned unchanged.
        assert set(unresolved) == {99}
        assert watermark == 10
        assert records_read == 0

    def test_merges_records_after_watermark(self, test_domain):
        """The normal case: the snapshot is kept and only records after the
        watermark are merged. A record at or below the watermark is not re-read."""
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            # Three failed-stream records at per-stream positions 0, 1, 2.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 7)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 8)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 9)
            # Watermark 2: positions 0, 1 are already accounted for; only the
            # record at position 2 (global 9) is after it.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=2,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            unresolved, watermark, records_read = reconstruct_unresolved(
                store,
                "recovery-checkpoint-Handler-order",
                "failed-Handler-order",
            )

        # Snapshot (5) kept; only the record after the watermark (9) merged in;
        # positions 7, 8 (at/below the watermark) not re-read.
        assert set(unresolved) == {5, 9}
        assert watermark == 3
        assert records_read == 1

    @pytest.mark.no_test_domain
    def test_record_without_position_raises(self):
        """A failed record whose last page entry carries no per-stream position
        cannot advance the cursor. Rather than silently return a partial scan as
        if complete, it raises so the CLI reports the subscription unverified."""
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = MagicMock()
        store._read_last_message.return_value = None  # no checkpoint
        msg = MagicMock()
        msg.data.get.side_effect = lambda k, default=None: {
            "position": 5,
            "retry_count": 0,
            "stream_name": None,
            "stream_position": None,
        }.get(k, default)
        msg.metadata.headers.type = "Failed"
        # A full page (page_size 1) whose only record lacks a per-stream position.
        msg.metadata.event_store.position = None
        store.read.return_value = [msg]

        with pytest.raises(ValueError, match="no per-stream position"):
            reconstruct_unresolved(store, "rec-stream", "failed-stream", page_size=1)

    @pytest.mark.no_test_domain
    def test_record_without_position_on_short_page_does_not_raise(self):
        """A positionless trailing record on a short (final) page does not raise:
        pagination is already complete, so no cursor advance is needed. The set is
        returned best-effort so one malformed trailing record does not fail
        subscription startup. (A full page in this state still raises.)"""
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = MagicMock()
        store._read_last_message.return_value = None  # no checkpoint
        msg = MagicMock()
        msg.data.get.side_effect = lambda k, default=None: {
            "position": 5,
            "retry_count": 0,
            "stream_name": None,
            "stream_position": None,
        }.get(k, default)
        msg.metadata.headers.type = "Failed"
        # A short page (one record, page_size 2) whose last record has no
        # per-stream position: pagination is done, so this stops without raising.
        msg.metadata.event_store.position = None
        store.read.return_value = [msg]

        unresolved, watermark, records_read = reconstruct_unresolved(
            store, "rec-stream", "failed-stream", page_size=2
        )

        # The record is still merged; the watermark does not advance (no position
        # to advance to); no exception.
        assert set(unresolved) == {5}
        assert watermark == 0
        assert records_read == 1

    @pytest.mark.no_test_domain
    def test_non_advancing_cursor_raises(self):
        """A full page whose last record does not move the cursor forward (a
        non-monotonic or duplicate position) would loop forever; it raises so the
        CLI reports the subscription unverified instead of hanging."""
        from protean.server.subscription.event_store_subscription import (
            reconstruct_unresolved,
        )

        store = MagicMock()
        store._read_last_message.return_value = None  # cursor starts at 0
        msg = MagicMock()
        msg.data.get.side_effect = lambda k, default=None: {
            "position": 9,
            "retry_count": 0,
            "stream_name": None,
            "stream_position": None,
        }.get(k, default)
        msg.metadata.headers.type = "Failed"
        # position + 1 == 0, not greater than the starting cursor 0: no progress.
        msg.metadata.event_store.position = -1
        # A full page that always comes back the same would loop without the guard.
        store.read.return_value = [msg]

        with pytest.raises(ValueError, match="did not advance"):
            reconstruct_unresolved(store, "rec-stream", "failed-stream", page_size=1)


class TestCheckpointAheadOfFailedStream:
    """The shared inconsistency check both the runtime rebuild and the CLI use."""

    @pytest.mark.no_test_domain
    def test_no_checkpoint_is_not_ahead(self):
        from protean.server.subscription.event_store_subscription import (
            checkpoint_ahead_of_failed_stream,
        )

        store = MagicMock()
        store._read_last_message.return_value = None  # no checkpoint
        assert checkpoint_ahead_of_failed_stream(store, "rec", "failed") is False

    @pytest.mark.no_test_domain
    def test_non_integer_watermark_is_not_ahead(self):
        """A corrupt checkpoint whose watermark is not an int is left for the
        reconstruction to handle, not read as ahead-of-stream (which would compare
        a string to an int and raise)."""
        from protean.server.subscription.event_store_subscription import (
            checkpoint_ahead_of_failed_stream,
        )

        store = MagicMock()
        store._read_last_message.return_value = {"data": {"watermark": "oops"}}
        assert checkpoint_ahead_of_failed_stream(store, "rec", "failed") is False


class TestCollectRecoveryCheckpointStatuses:
    def _seed_order_head(self, store) -> int:
        _seed_event(store, "order-1", "Placed", {"n": 1})
        _seed_event(store, "order-1", "Placed", {"n": 2})
        return store.stream_head_position("order")

    def test_flags_beyond_head_unresolved_entry(self, test_domain):
        """AC1: an unresolved entry past the head is named as stale."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "1": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].name == "sub"
        assert findings[0].handler_name == "Handler"
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]
        assert findings[0].head_position == head

    def test_checkpoint_ahead_of_failed_stream_is_unknown(self, test_domain):
        """A restore can leave the checkpoint watermark ahead of the failed
        stream it references. That state cannot be reconstructed reliably (the
        failed stream reuses positions after the truncation and the snapshot has
        no resolved-position tombstones), so the subscription is reported
        ``unknown`` rather than verified. Reset already refuses a non-stale
        finding, so it never touches an unverifiable checkpoint."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # Watermark 10 sits past the (empty) failed stream's tail (-1): the
            # checkpoint is ahead of the stream it references.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=10,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        assert findings[0].stale_positions == []

    def test_ahead_checkpoint_with_surviving_failed_row_is_unknown(self, test_domain):
        """Copilot's resurrection case, reported honestly. The history was
        ``Failed(5), Resolved(5)`` (position 5 resolved); a restore kept the
        checkpoint (watermark past both rows, snapshot excludes 5) but truncated
        the failed stream to the first row only. Rather than replay ``Failed(5)``
        and resurrect a resolved position (a duplicate delivery, or a false stale
        report), the inconsistent state is reported ``unknown``."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # Only the surviving Failed(5) row (per-stream position 0); its
            # Resolved(5) row was rolled back.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 5)
            # Checkpoint watermark 2 is past the truncated tail (0); its snapshot
            # correctly excludes 5.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=2,
                unresolved={},
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        # 5 is neither resurrected as unresolved nor falsely reported stale.
        assert findings[0].stale_positions == []

    def test_watermark_at_tail_is_not_flagged_unknown(self, test_domain):
        """A checkpoint whose watermark sits at the failed stream's tail+1 is the
        normal, consistent case, not an inconsistent restore. It is verified (its
        stale entry is reported stale), not reported unknown. Guards the ahead-of
        check against flagging a healthy checkpoint."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # Two failed-stream records -> tail per-stream position 1.
            _seed_failed_record(store, "failed-Handler-order", "Failed", 7)
            _seed_failed_record(store, "failed-Handler-order", "Failed", 8)
            # Watermark 2 == tail(1)+1: consistent, not ahead of the stream.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=2,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]

    def test_empty_category_head_minus_one_flags_every_tracked_position(
        self, test_domain
    ):
        """The maximal rollback leaves an empty category (head ``-1``); every
        tracked position is then past the head and flagged."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = store.stream_head_position("order")
            assert head == -1
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "0": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position="-1")]
        )

        assert len(findings) == 1
        assert findings[0].stale_positions == [0]

    def test_entry_at_or_below_head_not_flagged(self, test_domain):
        """AC4: entries at or below the head are left unreported."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "0": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert findings == []

    def test_stale_only_in_failed_stream_is_caught(self, test_domain):
        """A position that began failing after the last checkpoint lives only in
        the failed stream; reconstruction merges it and the re-read (no specific
        stream recorded, so the category stream at its position) finds nothing."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store, "recovery-checkpoint-Handler-order", watermark=0, unresolved={}
            )
            _seed_failed_record(store, "failed-Handler-order", "Failed", head + 7)

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].stale_positions == [head + 7]

    def test_removed_specific_stream_below_head_is_flagged(self, test_domain):
        """A failed record points at a specific stream a restore removed, but
        another aggregate has a later event so the category head stays above it.
        Comparing the global position to the head would miss it; re-reading the
        specific stream catches it."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)  # order-1 holds events; head == 2
            # A tracked position at global_position 1 (<= head) whose own stream
            # `order-removed` no longer exists.
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "1": {
                        "retry_count": 1,
                        "stream_name": "order-removed",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [1]

    def test_present_specific_stream_is_not_flagged(self, test_domain):
        """A tracked position whose specific stream still holds its message is
        healthy and left unreported, even below the head."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)  # order-1 holds events at pos 0, 1
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "1": {
                        "retry_count": 1,
                        "stream_name": "order-1",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert findings == []

    @pytest.mark.no_test_domain
    def test_non_event_store_subscription_skipped(self):
        # A broker subscription is skipped before any domain access.
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        findings = collect_recovery_checkpoint_statuses(
            None, [_rec_status(subscription_type="broker")]
        )
        assert findings == []

    def test_scans_when_read_position_head_is_unknown(self, test_domain):
        """The recovery lane reads the head itself, so it still runs and flags a
        stale entry when the read-position collection failed and left the status
        with no head (an unreadable read-position checkpoint must not hide
        readable recovery tracking)."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)  # store is readable
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )

        # head_position None models a read-position collection that failed but
        # still carried the derived recovery stream names.
        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=None)]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]
        # The head was read from the store, not taken from the (unknown) status.
        assert findings[0].head_position == head

    @pytest.mark.no_test_domain
    def test_missing_recovery_streams_skipped(self):
        # A status with no recovery streams is skipped before any domain access.
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        findings = collect_recovery_checkpoint_statuses(
            None, [_rec_status(recovery_checkpoint_stream=None)]
        )
        assert findings == []

    def test_no_tracking_returns_no_finding(self, test_domain):
        """An event-store subscription that never failed a position has no
        recovery streams to read, so it is not a finding."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )
        assert findings == []

    @pytest.mark.no_test_domain
    def test_store_read_failure_is_reported_unknown(self):
        """A store read that raises is reported as an unverified finding, not
        crashed and not silently folded into clean."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        mock_domain = MagicMock()
        store = mock_domain.event_store.store
        store._read_last_message.side_effect = RuntimeError("boom")
        # The head read also fails, so it falls back to the status head; a
        # non-numeric status head (a foreign store) is reported as -1 rather than
        # crashing the int parse.
        store.stream_head_position.side_effect = RuntimeError("head boom")
        findings = collect_recovery_checkpoint_statuses(
            mock_domain, [_rec_status(head_position="abc")]
        )
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        assert findings[0].stale_positions == []
        assert findings[0].head_position == -1

    @pytest.mark.no_test_domain
    def test_reuses_status_head_and_skips_the_store_read(self):
        """When the read-position collection already recorded a head, the recovery
        lane reuses it and does not pay a second (potentially expensive) store
        head read; the stale entry is still reported."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = MagicMock()
        # Would raise if the head were read; the test proves it is not.
        store.stream_head_position.side_effect = RuntimeError("head boom")
        # A checkpoint tracking one position, an empty failed stream, and a
        # re-read of that position that finds nothing (message gone -> stale).
        store._read_last_message.return_value = {
            "data": {
                "watermark": 0,
                "unresolved": {
                    "5": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    }
                },
            }
        }
        store.read.return_value = []
        mock_domain = MagicMock()
        mock_domain.event_store.store = store

        findings = collect_recovery_checkpoint_statuses(
            mock_domain, [_rec_status(head_position="7")]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [5]
        # The status head (7) was reused; the store head was never read.
        assert findings[0].head_position == 7
        store.stream_head_position.assert_not_called()

    @pytest.mark.no_test_domain
    def test_store_not_configured_is_reported_unknown(self):
        """A domain with no event store yields an unverified finding, not silence
        and not a raise."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        mock_domain = MagicMock()
        mock_domain.event_store.store = None
        findings = collect_recovery_checkpoint_statuses(mock_domain, [_rec_status()])
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"

    @pytest.mark.no_test_domain
    def test_corrupt_checkpoint_record_is_reported_unknown(self):
        """A restore can leave a checkpoint record whose ``data`` is malformed;
        the reconstruction raises and the subscription is reported unverified."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        mock_domain = MagicMock()
        # ``data`` is not a dict, so ``checkpoint["data"].get(...)`` raises.
        mock_domain.event_store.store._read_last_message.return_value = {
            "data": "not-a-dict"
        }
        findings = collect_recovery_checkpoint_statuses(mock_domain, [_rec_status()])
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"

    def test_read_error_on_one_position_keeps_confirmed_stale(self, test_domain):
        """A re-read that raises for one position must not discard the stale
        entries already confirmed for the same subscription."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # A metadata-less message makes ``store.read`` raise on that stream.
            store._write("order-corrupt", "Placed", {"n": 1})
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": "order-removed",
                        "stream_position": 0,
                    },
                    "6": {
                        "retry_count": 1,
                        "stream_name": "order-corrupt",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        # 5 (order-removed) is confirmed gone and reported; 6's read raised, so it
        # is skipped rather than dropping 5.
        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [5]

    def test_read_error_with_no_confirmed_stale_is_unknown(self, test_domain):
        """When the only re-read that could run raises and nothing is confirmed
        stale, the subscription is reported unverified rather than clean."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            store._write("order-corrupt", "Placed", {"n": 1})
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    "6": {
                        "retry_count": 1,
                        "stream_name": "order-corrupt",
                        "stream_position": 0,
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        assert len(findings) == 1
        assert findings[0].verdict == "unknown"

    def test_malformed_failed_record_is_skipped(self, test_domain):
        """A failed record missing its position is skipped, not merged as a
        phantom entry."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            # A record whose data carries no position at all.
            store._write(
                "failed-Handler-order",
                "Failed",
                {"position": None, "retry_count": 1},
                metadata={
                    "headers": {
                        "id": "x",
                        "type": "Failed",
                        "time": "2026-01-01T00:00:00+00:00",
                        "stream": "failed-Handler-order",
                    },
                    "domain": {
                        "kind": MessageType.READ_POSITION.value,
                        "origin_stream": "order",
                    },
                },
            )

        findings = collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )
        assert findings == []

    def test_collect_does_not_modify_any_stream(self, test_domain):
        """AC3: a verify-only collection never writes to the recovery stream."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            )
            before = store._read_last_message("recovery-checkpoint-Handler-order")

        collect_recovery_checkpoint_statuses(
            test_domain, [_rec_status(head_position=str(head))]
        )

        with test_domain.domain_context():
            after = store._read_last_message("recovery-checkpoint-Handler-order")

        # No new record appended: same global_position, same content.
        assert after["global_position"] == before["global_position"]
        assert after["data"] == before["data"]


class TestResetRecoveryCheckpoint:
    def _seed_order_head(self, store) -> int:
        _seed_event(store, "order-1", "Placed", {"n": 1})
        _seed_event(store, "order-1", "Placed", {"n": 2})
        return store.stream_head_position("order")

    def test_drops_stale_keeps_healthy_and_reverifies_clean(self, test_domain):
        """AC2 round-trip: the reset drops the beyond-head entries, keeps the
        at-or-below-head ones, and a later collection finds nothing."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
            reset_recovery_checkpoint,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=0,
                unresolved={
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "1": {
                        "retry_count": 2,
                        "stream_name": "order-1",
                        "stream_position": 0,
                    },
                },
            )

        status = _rec_status(head_position=str(head))
        findings = collect_recovery_checkpoint_statuses(test_domain, [status])
        assert findings[0].stale_positions == [head + 3]

        cleared = reset_recovery_checkpoint(test_domain, findings[0])
        assert cleared == [head + 3]

        # The healthy entry survived, the stale one is gone.
        with test_domain.domain_context():
            last = store._read_last_message("recovery-checkpoint-Handler-order")
        assert set(last["data"]["unresolved"]) == {"1"}

        # A later collection is clean.
        assert collect_recovery_checkpoint_statuses(test_domain, [status]) == []

    def test_reset_holds_when_stale_only_in_failed_stream(self, test_domain):
        """A stale position present only in the failed stream is cleared and the
        watermark is advanced past it, so a later collection stays clean."""
        from protean.server.subscription_status import (
            collect_recovery_checkpoint_statuses,
            reset_recovery_checkpoint,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            head = self._seed_order_head(store)
            _seed_recovery_checkpoint(
                store, "recovery-checkpoint-Handler-order", watermark=0, unresolved={}
            )
            _seed_failed_record(store, "failed-Handler-order", "Failed", head + 7)

        status = _rec_status(head_position=str(head))
        findings = collect_recovery_checkpoint_statuses(test_domain, [status])
        assert findings[0].stale_positions == [head + 7]

        reset_recovery_checkpoint(test_domain, findings[0])

        # The rewritten checkpoint carries a watermark past the failed record, so
        # reconstruction no longer re-reads it.
        with test_domain.domain_context():
            last = store._read_last_message("recovery-checkpoint-Handler-order")
        assert last["data"]["watermark"] == 1
        assert last["data"]["unresolved"] == {}
        assert collect_recovery_checkpoint_statuses(test_domain, [status]) == []

    @pytest.mark.no_test_domain
    def test_raises_when_store_not_configured(self):
        from protean.server.subscription_status import (
            RecoveryCheckpointStatus,
            reset_recovery_checkpoint,
        )

        mock_domain = MagicMock()
        mock_domain.event_store.store = None

        finding = RecoveryCheckpointStatus(
            name="sub",
            handler_name="Handler",
            stream_category="order",
            recovery_checkpoint_stream="recovery-checkpoint-Handler-order",
            head_position=2,
            verdict="stale",
            stale_positions=[5],
            unresolved={
                5: {"retry_count": 1, "stream_name": None, "stream_position": None}
            },
            watermark=0,
        )
        with pytest.raises(ValueError, match="no event store"):
            reset_recovery_checkpoint(mock_domain, finding)

    def test_refuses_to_reset_an_unknown_finding(self, test_domain):
        """An unknown finding carries an empty snapshot, so resetting it would
        wipe the subscription's real recovery state. It is refused, and the real
        checkpoint is left untouched."""
        from protean.server.subscription_status import (
            RecoveryCheckpointStatus,
            reset_recovery_checkpoint,
        )

        store = test_domain.event_store.store
        with test_domain.domain_context():
            _seed_recovery_checkpoint(
                store,
                "recovery-checkpoint-Handler-order",
                watermark=3,
                unresolved={
                    "5": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    }
                },
            )
            before = store._read_last_message("recovery-checkpoint-Handler-order")

        finding = RecoveryCheckpointStatus(
            name="sub",
            handler_name="Handler",
            stream_category="order",
            recovery_checkpoint_stream="recovery-checkpoint-Handler-order",
            head_position=2,
            verdict="unknown",
            stale_positions=[],
            unresolved={},
            watermark=0,
        )
        with pytest.raises(ValueError, match="not 'stale'"):
            reset_recovery_checkpoint(test_domain, finding)

        # The real snapshot was not overwritten with the finding's empty one.
        with test_domain.domain_context():
            after = store._read_last_message("recovery-checkpoint-Handler-order")
        assert after["data"] == before["data"]
