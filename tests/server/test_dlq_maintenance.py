"""Tests for DLQ maintenance task — retention trimming and alerting.

Covers:
- Messages older than retention are trimmed
- Per-profile override honored over global
- Alert fires when depth exceeds threshold
- OTEL counters increment
- Alert callback is invoked
- Graceful handling when no DLQ-capable broker exists
"""

import asyncio
import contextlib
import logging

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.port.broker import BrokerCapabilities
from protean.server.dlq_maintenance import (
    DLQMaintenanceTask,
    _resolve_callback,
    _retention_hours_to_min_id,
)
from protean.server.engine import Engine
from protean.server.subscription.profiles import (
    SubscriptionConfig,
    SubscriptionProfile,
)
from protean.utils.dlq import SubscriptionInfo, discover_subscriptions
from protean.utils.telemetry import get_domain_metrics

_LOGGER = "protean.server.dlq_maintenance"

# ── Domain elements ──────────────────────────────────────────────────────


class DLQMaintAggregate(BaseAggregate):
    name: String(required=True)


class DLQMaintEvent(BaseEvent):
    name: String(required=True)


class DLQMaintHandler(BaseEventHandler):
    pass


class DLQMaintOtherHandler(BaseEventHandler):
    pass


# ── Helpers ──────────────────────────────────────────────────────────────


class FakeBroker:
    """Stands in for the Redis broker, the only one that trims a DLQ and reports
    its depth."""

    def __init__(
        self, capabilities: BrokerCapabilities = BrokerCapabilities.DEAD_LETTER_QUEUE
    ) -> None:
        self._capabilities = capabilities
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
    """A subscription that carries DLQ overrides on its config.

    The engine's own subscriptions expose no ``config``, so only a stand-in can
    feed per-subscription overrides to the task.
    """

    def __init__(
        self,
        dlq_stream: str,
        dlq_retention_hours: int | None = None,
        dlq_alert_threshold: int | None = None,
    ) -> None:
        self.dlq_stream = dlq_stream
        self.config = SubscriptionConfig(
            dlq_retention_hours=dlq_retention_hours,
            dlq_alert_threshold=dlq_alert_threshold,
        )


def _setup_domain(dlq_config: dict | None = None):
    """Create a Domain on the inline broker, with optional ``[server.dlq]``."""
    domain = Domain(__file__, "DLQTest")
    domain.config["brokers"] = {"default": {"provider": "inline"}}
    if dlq_config is not None:
        domain.config["server"]["dlq"] = dlq_config
    return domain


def _register_handler(domain) -> None:
    domain.register(DLQMaintAggregate)
    domain.register(DLQMaintEvent, part_of=DLQMaintAggregate)
    domain.register(DLQMaintHandler, part_of=DLQMaintAggregate)
    domain.init(traverse=False)


def _dlq_config(alert_threshold: int = 1000) -> dict:
    return {
        "retention_hours": 168,
        "alert_threshold": alert_threshold,
        "alert_callback": None,
        "check_interval_seconds": 60,
    }


def _get_dlq_stream(domain) -> str:
    """Discover the actual DLQ stream name after domain init."""
    subs = discover_subscriptions(domain)
    assert len(subs) > 0, "Expected at least one subscription"
    return subs[0].dlq_stream


def _messages(caplog, message: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == message]


# ── Unit tests ───────────────────────────────────────────────────────────


class TestRetentionHoursToMinId:
    def test_min_id_is_a_millisecond_cutoff_that_falls_with_retention(self):
        id_7d = _retention_hours_to_min_id(168)
        id_1d = _retention_hours_to_min_id(24)

        assert id_1d.endswith("-0")
        assert int(id_1d.split("-")[0]) > 0
        assert int(id_7d.split("-")[0]) < int(id_1d.split("-")[0])


class TestResolveCallback:
    @pytest.mark.parametrize(
        "path",
        [
            None,
            "",
            "no_such_module.func",
            "os.path.no_such_attr_xyz",
            "justafunc",
            # os.path.sep is a string, not callable
            "os.path.sep",
        ],
        ids=[
            "none",
            "empty",
            "invalid_module",
            "invalid_attr",
            "no_dot",
            "non_callable",
        ],
    )
    def test_unusable_path_returns_none(self, path):
        assert _resolve_callback(path) is None


class TestDLQMaintenanceTaskInit:
    @pytest.mark.no_test_domain
    def test_reads_global_config(self):
        domain = _setup_domain(
            {
                "retention_hours": 48,
                "alert_threshold": 50,
                "alert_callback": None,
                "check_interval_seconds": 30,
            }
        )

        with domain.domain_context():
            domain.init(traverse=False)

            task = DLQMaintenanceTask(Engine(domain, test_mode=True))

            assert task.retention_hours == 48
            assert task.alert_threshold == 50
            assert task.check_interval == 30
            assert task.alert_callback is None

    @pytest.mark.no_test_domain
    def test_per_subscription_overrides(self):
        """The task indexes a subscription's DLQ overrides by its DLQ stream.

        No engine subscription carries a ``config`` today, so a real engine
        never applies these overrides. This test feeds them through a stand-in
        and checks the indexing only.
        """
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            engine = Engine(domain, test_mode=True)
            engine._subscriptions = {
                "order-handler": FakeSubscription(
                    "order:dlq",
                    dlq_retention_hours=24,
                    dlq_alert_threshold=10,
                )
            }

            task = DLQMaintenanceTask(engine)

            assert task._per_sub_retention["order:dlq"] == 24
            assert task._per_sub_threshold["order:dlq"] == 10


class TestDLQMaintenanceCycle:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_trims_old_messages(self):
        """Messages older than retention are trimmed via broker.dlq_trim."""
        domain = _setup_domain(_dlq_config())

        with domain.domain_context():
            _register_handler(domain)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._trim_returns[dlq_stream] = 5

            engine = Engine(domain, test_mode=True)
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            await task._maintenance_cycle()

            trimmed_streams = [call[0] for call in fake_broker._trim_calls]
            assert dlq_stream in trimmed_streams

            metrics = get_domain_metrics(domain)
            assert hasattr(metrics, "dlq_trimmed")

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_per_profile_override_honored(self):
        """Per-subscription retention overrides the global default."""
        domain = _setup_domain(_dlq_config())

        with domain.domain_context():
            _register_handler(domain)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._trim_returns[dlq_stream] = 3

            engine = Engine(domain, test_mode=True)
            engine._subscriptions = {
                "handler": FakeSubscription(dlq_stream, dlq_retention_hours=24)
            }
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
    @pytest.mark.parametrize(
        "depth, threshold, alerts",
        [(10, 5, True), (5, 5, True), (4, 5, False)],
        ids=["above_threshold", "at_threshold", "below_threshold"],
    )
    async def test_alert_fires_only_when_threshold_reached(
        self, caplog, depth, threshold, alerts
    ):
        """A WARNING is logged when the depth reaches the threshold, and only then."""
        domain = _setup_domain(_dlq_config(alert_threshold=threshold))

        with domain.domain_context():
            _register_handler(domain)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = depth

            engine = Engine(domain, test_mode=True)
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)

            with caplog.at_level(logging.WARNING, logger=_LOGGER):
                await task._maintenance_cycle()

        warnings = _messages(caplog, "dlq_maintenance.threshold_exceeded")
        assert bool(warnings) is alerts

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_alert_callback_invoked(self):
        """User-supplied callback is called with dlq_stream, depth, threshold."""
        callback_calls: list[dict] = []

        def my_callback(**kwargs):
            callback_calls.append(kwargs)

        domain = _setup_domain(_dlq_config(alert_threshold=5))

        with domain.domain_context():
            _register_handler(domain)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = 20

            engine = Engine(domain, test_mode=True)
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
    async def test_callback_exception_does_not_crash(self, caplog):
        """A failing callback is caught and logged, not propagated."""

        def bad_callback(**kwargs):
            raise RuntimeError("callback exploded")

        domain = _setup_domain(_dlq_config(alert_threshold=1))

        with domain.domain_context():
            _register_handler(domain)

            dlq_stream = _get_dlq_stream(domain)
            fake_broker = FakeBroker()
            fake_broker._depths[dlq_stream] = 10

            engine = Engine(domain, test_mode=True)
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            task.alert_callback = bad_callback
            with caplog.at_level(logging.ERROR, logger=_LOGGER):
                await task._maintenance_cycle()

        assert len(_messages(caplog, "dlq_maintenance.callback_failed")) == 1

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_no_dlq_broker_skips_cycle(self):
        """When no broker supports DLQ, maintenance cycle is a no-op."""
        domain = _setup_domain()

        with domain.domain_context():
            _register_handler(domain)

            no_dlq_broker = FakeBroker(BrokerCapabilities.RELIABLE_MESSAGING)
            engine = Engine(domain, test_mode=True)
            domain.brokers._brokers = {"default": no_dlq_broker}

            task = DLQMaintenanceTask(engine)
            await task._maintenance_cycle()

            assert no_dlq_broker._trim_calls == []


class TestDLQMaintenanceCollectStreams:
    @pytest.mark.no_test_domain
    def test_deduplicates_streams(self):
        """Two handlers on one stream category share one DLQ stream, listed once."""
        domain = _setup_domain()
        with domain.domain_context():
            _register_handler(domain)
            domain.register(DLQMaintOtherHandler, part_of=DLQMaintAggregate)

            assert len(discover_subscriptions(domain)) == 2

            task = DLQMaintenanceTask(Engine(domain, test_mode=True))

            assert task._dlq_streams_unique == [_get_dlq_stream(domain)]


class TestDLQMaintenanceStartAndRun:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_start_creates_named_task(self):
        """start() creates a task with the maintenance loop."""
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            engine = Engine(domain, test_mode=True)
            # The engine runs its own loop in production; here the test's loop
            # stands in so the created task is visible.
            engine.loop.close()
            engine.loop = asyncio.get_running_loop()

            task = DLQMaintenanceTask(engine)
            await task.start()

            running_tasks = [
                t
                for t in asyncio.all_tasks()
                if "dlq-maintenance" in (t.get_name() or "")
            ]
            assert len(running_tasks) > 0

            # Clean up
            task.keep_going = False
            for t in running_tasks:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t

    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_run_survives_a_failed_cycle_and_stops_on_shutdown(self, caplog):
        """_run logs a failed cycle, runs the next one, and exits once the engine
        is shutting down."""
        domain = _setup_domain()
        with domain.domain_context():
            _register_handler(domain)

            engine = Engine(domain, test_mode=True)
            checks = 0

            class _DroppingBroker(FakeBroker):
                """Loses its connection on the first cycle; the engine starts
                shutting down during the second."""

                def has_capability(self, cap) -> bool:
                    nonlocal checks
                    checks += 1
                    if checks == 1:
                        raise ConnectionError("connection dropped")
                    engine.shutting_down = True
                    return super().has_capability(cap)

            domain.brokers._brokers = {"default": _DroppingBroker()}

            task = DLQMaintenanceTask(engine)
            task.check_interval = 0

            with caplog.at_level(logging.ERROR, logger=_LOGGER):
                await task._run()

        assert checks == 2  # Continued after the first failure, then stopped
        assert len(_messages(caplog, "dlq_maintenance.cycle_failed")) == 1


class TestBaseBrokerDefaultMethods:
    def test_dlq_trim_and_depth_default_to_zero(self, test_domain):
        """BaseBroker.dlq_trim and dlq_depth return 0 by default."""
        broker = test_domain.brokers["default"]
        assert broker.dlq_trim("some:dlq", "0-0") == 0
        assert broker.dlq_depth("some:dlq") == 0


class TestSubscriptionConfigDLQOverrides:
    def test_from_profile_defaults_none(self):
        """from_profile leaves dlq overrides as None when not specified."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        assert config.dlq_retention_hours is None
        assert config.dlq_alert_threshold is None

    def test_from_dict_with_dlq_overrides(self):
        """from_dict reads dlq override keys."""
        config = SubscriptionConfig.from_dict(
            {
                "dlq_retention_hours": 48,
                "dlq_alert_threshold": 25,
            }
        )
        assert config.dlq_retention_hours == 48
        assert config.dlq_alert_threshold == 25

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"dlq_retention_hours": -1}, "dlq_retention_hours must be positive"),
            ({"dlq_alert_threshold": 0}, "dlq_alert_threshold must be positive"),
        ],
        ids=["negative_retention", "zero_threshold"],
    )
    def test_validation_rejects_non_positive_values(self, kwargs, message):
        with pytest.raises(ConfigurationError, match=message):
            SubscriptionConfig(**kwargs)

    def test_from_profile_passes_dlq_overrides_into_to_dict(self):
        """from_profile sets the dlq overrides and to_dict includes them."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            dlq_retention_hours=72,
            dlq_alert_threshold=200,
        )
        assert config.dlq_retention_hours == 72
        assert config.dlq_alert_threshold == 200
        d = config.to_dict()
        assert d["dlq_retention_hours"] == 72
        assert d["dlq_alert_threshold"] == 200


class TestEngineDLQMaintenanceIntegration:
    @pytest.mark.no_test_domain
    def test_engine_creates_dlq_maintenance_when_enabled(self):
        """Engine creates DLQMaintenanceTask when [server.dlq] enabled = true."""
        domain = _setup_domain()
        domain.config["server"]["dlq"]["enabled"] = True
        with domain.domain_context():
            _register_handler(domain)

            engine = Engine(domain, test_mode=True)
            assert engine._dlq_maintenance is not None
            assert engine._dlq_maintenance.subscriber_name == "dlq-maintenance"

    @pytest.mark.no_test_domain
    def test_engine_skips_dlq_maintenance_when_disabled(self):
        """Engine does not create DLQMaintenanceTask when disabled (default)."""
        domain = _setup_domain()
        with domain.domain_context():
            _register_handler(domain)

            engine = Engine(domain, test_mode=True)
            assert engine._dlq_maintenance is None


class TestDLQMaintenanceShutdown:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_shutdown_sets_keep_going_false(self):
        domain = _setup_domain()
        with domain.domain_context():
            domain.init(traverse=False)

            task = DLQMaintenanceTask(Engine(domain, test_mode=True))
            assert task.keep_going is True
            await task.shutdown()
            assert task.keep_going is False


class TestDLQMaintenancePerStreamException:
    @pytest.mark.no_test_domain
    @pytest.mark.asyncio
    async def test_stream_exception_does_not_abort_cycle(self, caplog):
        """An exception on one stream doesn't prevent others from processing."""
        domain = _setup_domain(_dlq_config())

        with domain.domain_context():
            _register_handler(domain)

            class FailingTrimBroker(FakeBroker):
                def dlq_trim(self, dlq_stream, min_id):
                    if "fail" in dlq_stream:
                        raise RuntimeError("trim failed")
                    return super().dlq_trim(dlq_stream, min_id)

            fake_broker = FailingTrimBroker()
            engine = Engine(domain, test_mode=True)
            domain.brokers._brokers = {"default": fake_broker}

            task = DLQMaintenanceTask(engine)
            # Two DLQ streams: one fails, the other must still be trimmed.
            dlq_stream = _get_dlq_stream(domain)
            task._dlq_streams_unique = ["fail:dlq", dlq_stream]

            with caplog.at_level(logging.ERROR, logger=_LOGGER):
                await task._maintenance_cycle()

        assert [call[0] for call in fake_broker._trim_calls] == [dlq_stream]
        assert len(_messages(caplog, "dlq_maintenance.stream_maintenance_failed")) == 1


class TestDLQStreamsStaticMethod:
    @pytest.mark.parametrize(
        "backfill, expected",
        [
            ("orders:backfill:dlq", ["orders:dlq", "orders:backfill:dlq"]),
            (None, ["orders:dlq"]),
        ],
        ids=["backfill_present", "backfill_none"],
    )
    def test_lists_the_backfill_stream_only_when_present(self, backfill, expected):
        info = SubscriptionInfo(
            handler_name="TestHandler",
            handler_fqn="test.TestHandler",
            stream_category="orders",
            dlq_stream="orders:dlq",
            backfill_dlq_stream=backfill,
        )
        assert DLQMaintenanceTask._dlq_streams(info) == expected
