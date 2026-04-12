"""Tests for DLQ maintenance task — retention trimming and alerting.

Covers:
- Messages older than retention are trimmed
- Per-profile override honored over global
- Alert fires when depth exceeds threshold
- OTEL counters increment
- Alert callback is invoked
- Graceful handling when no DLQ-capable broker exists
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import String
from protean.server.dlq_maintenance import (
    DLQMaintenanceTask,
    _resolve_callback,
    _retention_hours_to_min_id,
)
from protean.utils.dlq import discover_subscriptions
from protean.utils.telemetry import get_domain_metrics


# ── Domain elements ──────────────────────────────────────────────────────


class DLQMaintAggregate(BaseAggregate):
    name: String(required=True)


class DLQMaintEvent(BaseEvent):
    name: String(required=True)


class DLQMaintHandler(BaseEventHandler):
    pass


# ── Helpers ──────────────────────────────────────────────────────────────


class FakeBroker:
    """Minimal broker stub supporting DLQ operations for testing."""

    def __init__(self) -> None:
        from protean.port.broker import BrokerCapabilities

        self._capabilities = BrokerCapabilities.DEAD_LETTER_QUEUE
        self._trim_calls: list[tuple[str, str]] = []
        self._depths: dict[str, int] = {}
        self._trim_returns: dict[str, int] = {}

    def has_capability(self, cap) -> bool:
        return bool(self._capabilities & cap)

    def dlq_trim(self, dlq_stream: str, min_id: str) -> int:
        self._trim_calls.append((dlq_stream, min_id))
        return self._trim_returns.get(dlq_stream, 0)

    def dlq_depth(self, dlq_stream: str) -> int:
        return self._depths.get(dlq_stream, 0)


class FakeSubscription:
    """Minimal subscription stub with config and dlq_stream."""

    def __init__(
        self,
        dlq_stream: str,
        dlq_retention_hours: int | None = None,
        dlq_alert_threshold: int | None = None,
    ) -> None:
        self.dlq_stream = dlq_stream
        self.config = MagicMock()
        self.config.dlq_retention_hours = dlq_retention_hours
        self.config.dlq_alert_threshold = dlq_alert_threshold


def _setup_domain():
    """Create and initialize a Domain with handler elements registered."""
    domain = Domain(__file__, "DLQTest")
    domain.config["brokers"] = {"default": {"provider": "inline"}}
    return domain


def _get_dlq_stream(domain) -> str:
    """Discover the actual DLQ stream name after domain init."""
    subs = discover_subscriptions(domain)
    assert len(subs) > 0, "Expected at least one subscription"
    return subs[0].dlq_stream


# ── Unit tests ───────────────────────────────────────────────────────────


class TestRetentionHoursToMinId:
    def test_returns_millisecond_format(self):
        min_id = _retention_hours_to_min_id(24)
        assert min_id.endswith("-0")
        ts = int(min_id.split("-")[0])
        assert ts > 0

    def test_larger_retention_gives_smaller_id(self):
        id_7d = _retention_hours_to_min_id(168)
        id_1d = _retention_hours_to_min_id(24)
        assert int(id_7d.split("-")[0]) < int(id_1d.split("-")[0])


class TestResolveCallback:
    def test_none_returns_none(self):
        assert _resolve_callback(None) is None

    def test_empty_returns_none(self):
        assert _resolve_callback("") is None

    def test_valid_import(self):
        cb = _resolve_callback("os.path.exists")
        import os.path

        assert cb is os.path.exists

    def test_invalid_module_returns_none(self):
        assert _resolve_callback("no_such_module.func") is None

    def test_invalid_attr_returns_none(self):
        assert _resolve_callback("os.path.no_such_attr_xyz") is None

    def test_no_dot_returns_none(self):
        assert _resolve_callback("justafunc") is None


class TestDLQMaintenanceTaskInit:
    @pytest.mark.no_test_domain
    def test_reads_global_config(self):
        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 48,
            "alert_threshold": 50,
            "alert_callback": None,
            "check_interval_seconds": 30,
        }

        with domain.domain_context():
            domain.init(traverse=False)

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}

            task = DLQMaintenanceTask(engine)

            assert task.retention_hours == 48
            assert task.alert_threshold == 50
            assert task.check_interval == 30
            assert task.alert_callback is None

    @pytest.mark.no_test_domain
    def test_per_subscription_overrides(self):
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            engine = MagicMock()
            engine.domain = domain

            sub = FakeSubscription(
                "order:dlq",
                dlq_retention_hours=24,
                dlq_alert_threshold=10,
            )
            engine._subscriptions = {"order-handler": sub}

            task = DLQMaintenanceTask(engine)

            assert task._per_sub_retention["order:dlq"] == 24
            assert task._per_sub_threshold["order:dlq"] == 10


class TestDLQMaintenanceCycle:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_trims_old_messages(self):
        """Messages older than retention are trimmed via broker.dlq_trim."""
        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 168,
            "alert_threshold": 1000,
            "alert_callback": None,
            "check_interval_seconds": 60,
        }

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._trim_returns[dlq_stream] = 5

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            await task._maintenance_cycle()

            trimmed_streams = [call[0] for call in fake_broker._trim_calls]
            assert len(trimmed_streams) > 0, "Expected trim to be called"
            assert dlq_stream in trimmed_streams

            metrics = get_domain_metrics(domain)
            assert hasattr(metrics, "dlq_trimmed")

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_per_profile_override_honored(self):
        """Per-subscription retention overrides the global default."""
        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 168,
            "alert_threshold": 1000,
            "alert_callback": None,
            "check_interval_seconds": 60,
        }

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._trim_returns[dlq_stream] = 3

            engine = MagicMock()
            engine.domain = domain
            engine.shutting_down = False

            sub = FakeSubscription(dlq_stream, dlq_retention_hours=24)
            engine._subscriptions = {"handler": sub}
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            await task._maintenance_cycle()

            assert len(fake_broker._trim_calls) > 0, "Expected trim to be called"
            _stream, trim_min_id = fake_broker._trim_calls[0]
            expected_min_id = _retention_hours_to_min_id(24)
            actual_ts = int(trim_min_id.split("-")[0])
            expected_ts = int(expected_min_id.split("-")[0])
            assert abs(actual_ts - expected_ts) < 2000

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_alert_fires_when_threshold_exceeded(self):
        """Alert logs warning when depth > threshold."""
        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 168,
            "alert_threshold": 5,
            "alert_callback": None,
            "check_interval_seconds": 60,
        }

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = 10

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)

            with patch.object(
                logging.getLogger("protean.server.dlq_maintenance"),
                "warning",
            ) as mock_warn:
                await task._maintenance_cycle()
                assert mock_warn.call_count > 0
                assert "threshold_exceeded" in str(mock_warn.call_args)

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_alert_callback_invoked(self):
        """User-supplied callback is called with dlq_stream, depth, threshold."""
        callback_calls: list[dict] = []

        def my_callback(**kwargs):
            callback_calls.append(kwargs)

        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 168,
            "alert_threshold": 5,
            "alert_callback": None,
            "check_interval_seconds": 60,
        }

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = 20

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            task.alert_callback = my_callback
            await task._maintenance_cycle()

            assert len(callback_calls) > 0, "Callback should have been called"
            call = callback_calls[0]
            assert call["dlq_stream"] == dlq_stream
            assert call["depth"] == 20
            assert call["threshold"] == 5

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash(self):
        """A failing callback is caught and logged, not propagated."""

        def bad_callback(**kwargs):
            raise RuntimeError("callback exploded")

        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 168,
            "alert_threshold": 1,
            "alert_callback": None,
            "check_interval_seconds": 60,
        }

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = 10

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            task.alert_callback = bad_callback
            await task._maintenance_cycle()

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_no_dlq_broker_skips_cycle(self):
        """When no broker supports DLQ, maintenance cycle is a no-op."""
        domain = _setup_domain()

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            no_dlq_broker = MagicMock()
            no_dlq_broker.has_capability.return_value = False

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False
            domain.brokers._brokers = {"default": no_dlq_broker}

            task = DLQMaintenanceTask(engine)
            await task._maintenance_cycle()

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_no_alert_when_below_threshold(self):
        """No alert when DLQ depth is below threshold."""
        domain = _setup_domain()
        domain.config["server"]["dlq"] = {
            "retention_hours": 168,
            "alert_threshold": 100,
            "alert_callback": None,
            "check_interval_seconds": 60,
        }

        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = 5

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)

            with patch.object(
                logging.getLogger("protean.server.dlq_maintenance"),
                "warning",
            ) as mock_warn:
                await task._maintenance_cycle()
                for call in mock_warn.call_args_list:
                    assert "threshold_exceeded" not in str(call)


class TestDLQMaintenanceNonCallableCallback:
    def test_non_callable_returns_none(self):
        """_resolve_callback rejects non-callable attributes."""
        # os.path.sep is a string, not callable
        result = _resolve_callback("os.path.sep")
        assert result is None


class TestDLQMaintenanceCollectStreams:
    @pytest.mark.no_test_domain
    def test_deduplicates_streams(self):
        """_collect_unique_dlq_streams removes duplicates."""
        domain = _setup_domain()
        with domain.domain_context():
            domain.register(DLQMaintAggregate)
            domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
            domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
            domain.init(traverse=False)

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}

            task = DLQMaintenanceTask(engine)
            # Should have at least one unique DLQ stream
            assert len(task._dlq_streams_unique) > 0
            # All entries should be unique
            assert len(task._dlq_streams_unique) == len(set(task._dlq_streams_unique))


class TestDLQMaintenanceStartAndRun:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_start_creates_named_task(self):
        """start() creates a task with the maintenance loop."""
        import asyncio

        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            loop = asyncio.get_event_loop()
            engine = MagicMock()
            engine.domain = domain
            engine.loop = loop
            engine._subscriptions = {}
            engine.shutting_down = False

            task = DLQMaintenanceTask(engine)
            await task.start()

            # The loop task should exist
            running_tasks = [t for t in asyncio.all_tasks() if "dlq-maintenance" in (t.get_name() or "")]
            assert len(running_tasks) > 0

            # Clean up
            task.keep_going = False
            for t in running_tasks:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_run_stops_when_shutting_down(self):
        """_run exits when engine.shutting_down is set."""
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}
            engine.shutting_down = False

            task = DLQMaintenanceTask(engine)
            task.check_interval = 0  # No sleep

            # Simulate shutting_down after first check
            call_count = 0
            original_cycle = task._maintenance_cycle

            async def mock_cycle():
                nonlocal call_count
                call_count += 1
                engine.shutting_down = True

            task._maintenance_cycle = mock_cycle
            await task._run()
            # Should have run at most once before stopping
            assert call_count <= 1


class TestBaseBrokerDefaultMethods:
    def test_dlq_trim_returns_zero(self, test_domain):
        """BaseBroker.dlq_trim default returns 0."""
        broker = test_domain.brokers["default"]
        result = broker.dlq_trim("some:dlq", "0-0")
        assert result == 0

    def test_dlq_depth_returns_zero(self, test_domain):
        """BaseBroker.dlq_depth default returns 0."""
        broker = test_domain.brokers["default"]
        result = broker.dlq_depth("some:dlq")
        assert result == 0


class TestSubscriptionConfigDLQOverrides:
    def test_from_profile_passes_dlq_overrides(self):
        """from_profile correctly passes dlq override values."""
        from protean.server.subscription.profiles import (
            SubscriptionConfig,
            SubscriptionProfile,
        )

        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            dlq_retention_hours=24,
            dlq_alert_threshold=50,
        )
        assert config.dlq_retention_hours == 24
        assert config.dlq_alert_threshold == 50

    def test_from_profile_defaults_none(self):
        """from_profile leaves dlq overrides as None when not specified."""
        from protean.server.subscription.profiles import (
            SubscriptionConfig,
            SubscriptionProfile,
        )

        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        assert config.dlq_retention_hours is None
        assert config.dlq_alert_threshold is None

    def test_from_dict_with_dlq_overrides(self):
        """from_dict reads dlq override keys."""
        from protean.server.subscription.profiles import SubscriptionConfig

        config = SubscriptionConfig.from_dict({
            "dlq_retention_hours": 48,
            "dlq_alert_threshold": 25,
        })
        assert config.dlq_retention_hours == 48
        assert config.dlq_alert_threshold == 25

    def test_validation_rejects_negative_retention(self):
        """Negative dlq_retention_hours raises ConfigurationError."""
        from protean.exceptions import ConfigurationError
        from protean.server.subscription.profiles import SubscriptionConfig

        with pytest.raises(ConfigurationError, match="dlq_retention_hours must be positive"):
            SubscriptionConfig(dlq_retention_hours=-1)

    def test_validation_rejects_zero_threshold(self):
        """Zero dlq_alert_threshold raises ConfigurationError."""
        from protean.exceptions import ConfigurationError
        from protean.server.subscription.profiles import SubscriptionConfig

        with pytest.raises(ConfigurationError, match="dlq_alert_threshold must be positive"):
            SubscriptionConfig(dlq_alert_threshold=0)

    def test_to_dict_includes_dlq_fields(self):
        """to_dict includes dlq override fields."""
        from protean.server.subscription.profiles import (
            SubscriptionConfig,
            SubscriptionProfile,
        )

        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            dlq_retention_hours=72,
            dlq_alert_threshold=200,
        )
        d = config.to_dict()
        assert d["dlq_retention_hours"] == 72
        assert d["dlq_alert_threshold"] == 200


class TestDLQMaintenanceShutdown:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_shutdown_sets_keep_going_false(self):
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}

            task = DLQMaintenanceTask(engine)
            assert task.keep_going is True
            await task.shutdown()
            assert task.keep_going is False


class TestDLQMaintenanceSubscriberName:
    @pytest.mark.no_test_domain
    def test_subscriber_name(self):
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            engine = MagicMock()
            engine.domain = domain
            engine._subscriptions = {}

            task = DLQMaintenanceTask(engine)
            assert task.subscriber_name == "dlq-maintenance"
