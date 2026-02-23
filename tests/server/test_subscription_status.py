"""Tests for subscription lag monitoring core module.

Tests cover the SubscriptionStatus dataclass, collection functions,
stream category inference, classification helpers, and graceful degradation
when infrastructure is unavailable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from protean.server.subscription_status import (
    SubscriptionStatus,
    _classify_status,
    _collect_broker_status,
    _collect_event_store_status,
    _collect_outbox_statuses,
    _collect_stream_status,
    _infer_stream_category,
    _unknown_status,
    collect_subscription_statuses,
)


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
        mock_domain.config.get.return_value = {"broker": "default"}
        mock_domain.providers.keys.return_value = ["default"]

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
        mock_domain.config.get.return_value = {"broker": "default"}
        mock_domain.providers.keys.return_value = ["default"]

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
        mock_domain.config.get.return_value = {"broker": "default"}
        mock_domain.providers.keys.return_value = ["default"]
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

    def test_redis_broker_xrange_exception_falls_back_to_pending(self):
        """When xrange fails on broker, lag falls back to pending count."""
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

        # Fallback: lag = pending
        assert result.lag == 3


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

    def test_xrange_exception_falls_back_to_pending(self):
        """When xrange fails, lag falls back to pending count."""
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

        # Fallback: lag = pending
        assert result.lag == 4

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
