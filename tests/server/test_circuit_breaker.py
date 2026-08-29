"""Tests for the per-subscription circuit breaker.

A ``StreamSubscription`` carries an in-memory circuit breaker that counts
consecutive handler-outcome failures and, once the threshold is reached, pauses
reads (state ``OPEN``) so a struggling downstream stops receiving new batches.
After a reset window it allows a single probe (``HALF_OPEN``); the probe's
outcome closes the breaker or re-opens it.

These tests cover:
- Opening at the threshold, and the read gate pausing reads while OPEN.
- ``poll()`` honoring the gate: an OPEN breaker skips the broker read entirely.
- The counter resetting on an intervening success (breaker does NOT open).
- Post-trip failures not re-emitting ``opened`` or restarting the timer.
- The HALF_OPEN probe: single-message reads (standard + both lane paths),
  closing on success, re-opening on failure with a restarted timer.
- Deserialization failures NOT counting as handler failures.
- A failing metric exporter not breaking message processing.
- Config resolution through the 7-level hierarchy plus round-trips.
- Validation of the two config keys, including non-finite reset windows.
- OTEL metric and trace emission on transitions, with matching negative cases.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Processing
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import (
    CircuitBreakerState,
    SubscriptionConfig,
    SubscriptionProfile,
)
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from protean.utils.telemetry import _DOMAIN_METRICS_KEY

_METRIC = "protean.subscription.circuit_breaker.state"

# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class User(BaseAggregate):
    email = String()
    name = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


class ToggleEventHandler(BaseEventHandler):
    """Fails when the event's ``name`` is ``"fail"``, succeeds otherwise.

    This lets a single subscription receive a controlled mix of success and
    failure outcomes through the real ``process_batch`` path.
    """

    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        if event.name == "fail":
            raise RuntimeError("Handler exploded")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockEngine:
    """Minimal engine mock that delegates handling to a real Engine."""

    def __init__(self, domain):
        self.domain = domain
        self.loop = asyncio.new_event_loop()
        self.emitter = Mock()
        self.shutting_down = False
        self.draining = False
        self._real_engine = Engine(domain, test_mode=True)

    async def handle_message(self, handler_cls, message, worker_id=None):
        return await self._real_engine.handle_message(
            handler_cls, message, worker_id=worker_id
        )


def _make_stream_subscription(test_domain, handler_cls=ToggleEventHandler, **overrides):
    """Create a StreamSubscription with a mock engine and mock broker."""
    engine = MockEngine(test_domain)
    sub = StreamSubscription(
        engine=engine,
        stream_category="test::user",
        handler=handler_cls,
        messages_per_tick=overrides.pop("messages_per_tick", 10),
        blocking_timeout_ms=100,
        max_retries=overrides.pop("max_retries", 50),
        retry_delay_seconds=overrides.pop("retry_delay_seconds", 0),
        enable_dlq=overrides.pop("enable_dlq", True),
        circuit_breaker_threshold=overrides.pop("circuit_breaker_threshold", 10),
        circuit_breaker_reset_seconds=overrides.pop(
            "circuit_breaker_reset_seconds", 60
        ),
    )
    broker = MagicMock()
    broker.ack = MagicMock(return_value=True)
    broker.nack = MagicMock(return_value=True)
    broker.publish = MagicMock()
    sub.broker = broker
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


def _message(name: str) -> tuple[str, dict]:
    """Build a serialized ``(id, payload)`` tuple. ``name="fail"`` fails."""
    identifier = str(uuid4())
    user = User(id=identifier, email="test@example.com", name=name)
    user.raise_(Registered(id=identifier, email="test@example.com", name=name))
    message = Message.from_domain_object(user._events[-1])
    return (identifier, message.to_dict())


def _init_telemetry_in_memory(domain):
    from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider

    resource = Resource.create({"service.name": domain.normalized_name})
    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])
    domain._otel_meter_provider = meter_provider
    domain._otel_tracer_provider = SDKTracerProvider(resource=resource)
    domain._otel_init_attempted = True
    return metric_reader


def _points_for_state(metric_reader, state: str) -> list:
    """Return circuit-breaker metric data points for a given ``state`` value."""
    data = metric_reader.get_metrics_data()
    return [
        point
        for resource_metric in data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
        if metric.name == _METRIC
        for point in metric.data.data_points
        if dict(point.attributes).get("state") == state
    ]


def _circuit_emit_events(emitter) -> list:
    """Return the circuit-breaker trace event names emitted on ``emitter``."""
    return [
        call.kwargs.get("event")
        for call in emitter.emit.call_args_list
        if str(call.kwargs.get("event", "")).startswith("subscription.circuit_breaker")
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def domain(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ToggleEventHandler, part_of=User)
    test_domain.init(traverse=False)
    yield test_domain
    if hasattr(test_domain, _DOMAIN_METRICS_KEY):
        delattr(test_domain, _DOMAIN_METRICS_KEY)


# ---------------------------------------------------------------------------
# Opening at the threshold + the read gate
# ---------------------------------------------------------------------------


class TestCircuitBreakerOpens:
    @pytest.mark.asyncio
    async def test_opens_after_threshold_consecutive_failures(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=3)

        batch = [_message("fail") for _ in range(3)]
        await sub.process_batch(batch, stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.OPEN
        assert sub.consecutive_handler_failures == 3
        assert sub.circuit_opened_at is not None

    @pytest.mark.asyncio
    async def test_stays_closed_below_threshold(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=3)

        batch = [_message("fail") for _ in range(2)]
        await sub.process_batch(batch, stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.CLOSED
        assert sub.consecutive_handler_failures == 2

    @pytest.mark.asyncio
    async def test_open_gate_pauses_reads_inside_reset_window(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_reset_seconds=30)
        # Force OPEN with the window almost — but not yet — elapsed, so the gate
        # sleeps a short slice and skips the read.
        sub.circuit_state = CircuitBreakerState.OPEN
        sub.circuit_opened_at = time.monotonic() - 29.95

        permitted = await sub._circuit_permits_reads()

        assert permitted is False
        assert sub.circuit_state == CircuitBreakerState.OPEN
        sub.broker.read_blocking.assert_not_called()
        sub.broker.ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_closed_gate_permits_reads(self, domain):
        sub = _make_stream_subscription(domain)
        assert await sub._circuit_permits_reads() is True

    @pytest.mark.asyncio
    async def test_threshold_one_opens_on_first_failure(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=1)

        await sub.process_batch([_message("fail")], stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.OPEN
        assert sub.consecutive_handler_failures == 1

    @pytest.mark.asyncio
    async def test_poll_skips_broker_read_while_open(self, domain):
        # Exercise the real poll() loop, not just the gate helper: an OPEN
        # breaker inside its reset window must skip the broker read entirely.
        sub = _make_stream_subscription(domain, circuit_breaker_reset_seconds=300)
        sub.broker.read_blocking = MagicMock(return_value=[])
        sub.circuit_state = CircuitBreakerState.OPEN
        sub.circuit_opened_at = time.monotonic()  # full window ahead, no probe

        task = asyncio.create_task(sub.poll())
        # Give poll() time to enter the loop and hit the OPEN gate a few times.
        await asyncio.sleep(0.1)
        task.cancel()
        await task  # poll() swallows CancelledError and returns

        sub.broker.read_blocking.assert_not_called()
        assert sub.circuit_state == CircuitBreakerState.OPEN

    async def test_poll_continues_past_read_when_gate_denies(self, domain):
        # Directly exercise the gate's `continue` in poll(): when the breaker
        # denies a read, the loop skips the read path and comes back around. The
        # sibling test above cancels while the real gate is mid-sleep, so it
        # never reaches this branch; here we make the gate return False fast (it
        # yields once so the loop can be cancelled) and confirm the read path is
        # never entered.
        sub = _make_stream_subscription(domain)
        sub.get_next_batch_of_messages = AsyncMock(return_value=[])

        async def _deny_reads() -> bool:
            await asyncio.sleep(0)  # yield so the task can be cancelled
            return False

        sub._circuit_permits_reads = _deny_reads

        task = asyncio.create_task(sub.poll())
        await asyncio.sleep(0.05)
        task.cancel()
        await task  # poll() swallows CancelledError and returns

        sub.get_next_batch_of_messages.assert_not_called()


# ---------------------------------------------------------------------------
# Reset on intervening success (negative case for "opens")
# ---------------------------------------------------------------------------


class TestCircuitBreakerResetsOnSuccess:
    @pytest.mark.asyncio
    async def test_intervening_success_resets_counter(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=3)

        # 2 fails, a success (resets), then 2 more fails: never 3 in a row.
        batch = [
            _message("fail"),
            _message("fail"),
            _message("ok"),
            _message("fail"),
            _message("fail"),
        ]
        await sub.process_batch(batch, stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.CLOSED
        assert sub.consecutive_handler_failures == 2

    @pytest.mark.asyncio
    async def test_no_open_emission_below_threshold(self, domain):
        metric_reader = _init_telemetry_in_memory(domain)
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=3)

        batch = [_message("fail"), _message("fail")]
        await sub.process_batch(batch, stream="test::user")

        assert _points_for_state(metric_reader, "opened") == []
        assert _circuit_emit_events(sub.engine.emitter) == []


# ---------------------------------------------------------------------------
# HALF_OPEN probe behavior
# ---------------------------------------------------------------------------


class TestCircuitBreakerHalfOpen:
    @pytest.mark.asyncio
    async def test_open_transitions_to_half_open_after_reset(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_reset_seconds=5)
        sub.circuit_state = CircuitBreakerState.OPEN
        # Opened well beyond the reset window.
        sub.circuit_opened_at = time.monotonic() - 10

        permitted = await sub._circuit_permits_reads()

        assert permitted is True
        assert sub.circuit_state == CircuitBreakerState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_reads_single_message(self, domain):
        sub = _make_stream_subscription(domain, messages_per_tick=25)
        sub.broker.read_blocking = MagicMock(return_value=[])

        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        await sub.get_next_batch_of_messages()

        assert sub.broker.read_blocking.call_args.kwargs["count"] == 1

    @pytest.mark.asyncio
    async def test_half_open_primary_lane_reads_single_message(self, domain):
        sub = _make_stream_subscription(domain, messages_per_tick=25)
        sub.broker.read_blocking = MagicMock(return_value=[])

        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        await sub._read_primary_nonblocking()

        assert sub.broker.read_blocking.call_args.kwargs["count"] == 1

    @pytest.mark.asyncio
    async def test_half_open_backfill_lane_reads_single_message(self, domain):
        sub = _make_stream_subscription(domain, messages_per_tick=25)
        sub.broker.read_blocking = MagicMock(return_value=[])

        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        await sub._read_backfill_blocking()

        assert sub.broker.read_blocking.call_args.kwargs["count"] == 1

    @pytest.mark.asyncio
    async def test_closed_reads_full_batch(self, domain):
        sub = _make_stream_subscription(domain, messages_per_tick=25)
        sub.broker.read_blocking = MagicMock(return_value=[])

        await sub.get_next_batch_of_messages()

        assert sub.broker.read_blocking.call_args.kwargs["count"] == 25

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self, domain):
        sub = _make_stream_subscription(domain)
        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        sub.circuit_opened_at = time.monotonic() - 100
        sub.consecutive_handler_failures = 5

        await sub.process_batch([_message("ok")], stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.CLOSED
        assert sub.consecutive_handler_failures == 0
        assert sub.circuit_opened_at is None

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_and_restarts_timer(self, domain):
        sub = _make_stream_subscription(domain)
        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        old_opened_at = time.monotonic() - 100
        sub.circuit_opened_at = old_opened_at

        await sub.process_batch([_message("fail")], stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.OPEN
        assert sub.circuit_opened_at is not None
        assert sub.circuit_opened_at > old_opened_at


# ---------------------------------------------------------------------------
# Deserialization failures do not count as handler failures
# ---------------------------------------------------------------------------


class TestCircuitBreakerIgnoresDeserializationFailures:
    @pytest.mark.asyncio
    async def test_poison_messages_do_not_trip_breaker(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=2)

        # Payloads that fail Message.deserialize are DLQ'd and skipped before
        # any handler runs, so they are not handler-outcome failures.
        batch = [(str(uuid4()), {"garbage": "value"}) for _ in range(5)]
        await sub.process_batch(batch, stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.CLOSED
        assert sub.consecutive_handler_failures == 0


# ---------------------------------------------------------------------------
# Config resolution (7-level hierarchy) + round-trips
# ---------------------------------------------------------------------------


class TestCircuitBreakerConfigResolution:
    def test_resolves_from_server_stream_subscription(self, test_domain):
        test_domain.config["server"]["stream_subscription"][
            "circuit_breaker_threshold"
        ] = 5
        test_domain.config["server"]["stream_subscription"][
            "circuit_breaker_reset_seconds"
        ] = 15

        @test_domain.event_handler(part_of=User)
        class Handler(BaseEventHandler):
            @handle(Registered)
            def on_registered(self, event: Registered) -> None:
                pass

        config = ConfigResolver(test_domain).resolve(Handler)

        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_reset_seconds == 15

    def test_handler_server_config_overrides_stream_defaults(self, test_domain):
        test_domain.config["server"]["stream_subscription"][
            "circuit_breaker_threshold"
        ] = 5
        test_domain.config["server"]["subscriptions"]["OverrideHandler"] = {
            "circuit_breaker_threshold": 7,
        }

        @test_domain.event_handler(part_of=User)
        class OverrideHandler(BaseEventHandler):
            @handle(Registered)
            def on_registered(self, event: Registered) -> None:
                pass

        config = ConfigResolver(test_domain).resolve(OverrideHandler)

        assert config.circuit_breaker_threshold == 7

    def test_handler_meta_overrides_server_config(self, test_domain):
        test_domain.config["server"]["subscriptions"]["MetaHandler"] = {
            "circuit_breaker_threshold": 7,
        }

        @test_domain.event_handler(
            part_of=User,
            subscription_config={"circuit_breaker_threshold": 9},
        )
        class MetaHandler(BaseEventHandler):
            @handle(Registered)
            def on_registered(self, event: Registered) -> None:
                pass

        config = ConfigResolver(test_domain).resolve(MetaHandler)

        assert config.circuit_breaker_threshold == 9

    def test_from_dict_round_trip(self):
        config = SubscriptionConfig.from_dict(
            {
                "circuit_breaker_threshold": 4,
                "circuit_breaker_reset_seconds": 12,
            }
        )
        assert config.circuit_breaker_threshold == 4
        assert config.circuit_breaker_reset_seconds == 12

    def test_from_dict_coerces_reset_seconds_to_float(self):
        # An int given for the float key is coerced, so to_dict/consumers see a
        # consistent float type.
        config = SubscriptionConfig.from_dict({"circuit_breaker_reset_seconds": 30})
        assert isinstance(config.circuit_breaker_reset_seconds, float)
        assert config.circuit_breaker_reset_seconds == 30.0

    def test_from_profile_override(self):
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            circuit_breaker_threshold=42,
        )
        assert config.circuit_breaker_threshold == 42
        # Reset seconds falls back to the profile default.
        assert config.circuit_breaker_reset_seconds == 60

    def test_to_dict_includes_keys(self):
        config = SubscriptionConfig(
            circuit_breaker_threshold=8, circuit_breaker_reset_seconds=20
        )
        as_dict = config.to_dict()
        assert as_dict["circuit_breaker_threshold"] == 8
        assert as_dict["circuit_breaker_reset_seconds"] == 20

    def test_from_config_threads_keys_to_subscription(self, test_domain):
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(ToggleEventHandler, part_of=User)
        test_domain.init(traverse=False)

        config = SubscriptionConfig(
            circuit_breaker_threshold=6, circuit_breaker_reset_seconds=18
        )
        engine = MockEngine(test_domain)
        sub = StreamSubscription.from_config(
            engine, "test::user", ToggleEventHandler, config
        )

        assert sub.circuit_breaker_threshold == 6
        assert sub.circuit_breaker_reset_seconds == 18


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestCircuitBreakerValidation:
    def test_threshold_zero_raises(self):
        with pytest.raises(ConfigurationError, match="circuit_breaker_threshold"):
            SubscriptionConfig(circuit_breaker_threshold=0)

    def test_threshold_negative_raises(self):
        with pytest.raises(ConfigurationError, match="circuit_breaker_threshold"):
            SubscriptionConfig(circuit_breaker_threshold=-1)

    def test_reset_seconds_zero_raises(self):
        with pytest.raises(ConfigurationError, match="circuit_breaker_reset_seconds"):
            SubscriptionConfig(circuit_breaker_reset_seconds=0)

    def test_reset_seconds_negative_raises(self):
        with pytest.raises(ConfigurationError, match="circuit_breaker_reset_seconds"):
            SubscriptionConfig(circuit_breaker_reset_seconds=-5)

    def test_reset_seconds_infinity_raises(self):
        # inf would OPEN the breaker forever — it never reaches HALF_OPEN.
        with pytest.raises(ConfigurationError, match="circuit_breaker_reset_seconds"):
            SubscriptionConfig(circuit_breaker_reset_seconds=float("inf"))

    def test_reset_seconds_nan_raises(self):
        # nan slips past `<= 0` and would silently disable the OPEN pause.
        with pytest.raises(ConfigurationError, match="circuit_breaker_reset_seconds"):
            SubscriptionConfig(circuit_breaker_reset_seconds=float("nan"))


# ---------------------------------------------------------------------------
# OTEL metric emission (positive + negative)
# ---------------------------------------------------------------------------


class TestCircuitBreakerMetrics:
    @pytest.mark.asyncio
    async def test_opened_records_metric(self, domain):
        metric_reader = _init_telemetry_in_memory(domain)
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=2)

        await sub.process_batch(
            [_message("fail"), _message("fail")], stream="test::user"
        )

        opened = _points_for_state(metric_reader, "opened")
        assert len(opened) == 1
        assert opened[0].value == 1
        assert dict(opened[0].attributes)["subscription"] == "ToggleEventHandler"

    @pytest.mark.asyncio
    async def test_closed_records_metric(self, domain):
        metric_reader = _init_telemetry_in_memory(domain)
        sub = _make_stream_subscription(domain)
        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        sub.circuit_opened_at = time.monotonic()

        await sub.process_batch([_message("ok")], stream="test::user")

        closed = _points_for_state(metric_reader, "closed")
        assert len(closed) == 1
        assert closed[0].value == 1

    @pytest.mark.asyncio
    async def test_no_metric_without_transition(self, domain):
        metric_reader = _init_telemetry_in_memory(domain)
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=5)

        await sub.process_batch([_message("ok"), _message("fail")], stream="test::user")

        data = metric_reader.get_metrics_data()
        names = [
            metric.name
            for rm in data.resource_metrics
            for sm in rm.scope_metrics
            for metric in sm.metrics
        ]
        assert _METRIC not in names

    @pytest.mark.asyncio
    async def test_failures_past_threshold_open_exactly_once(self, domain):
        # A batch that keeps failing well past the trip point must open the
        # breaker once and only once — no re-emit and no timer restart on each
        # subsequent failure while already OPEN.
        metric_reader = _init_telemetry_in_memory(domain)
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=3)

        batch = [_message("fail") for _ in range(3 + 4)]  # trip + 4 more
        await sub.process_batch(batch, stream="test::user")

        opened = _points_for_state(metric_reader, "opened")
        assert len(opened) == 1
        assert opened[0].value == 1  # a single .add, not one per post-trip failure
        assert (
            _circuit_emit_events(sub.engine.emitter).count(
                "subscription.circuit_breaker.opened"
            )
            == 1
        )
        assert sub.circuit_state == CircuitBreakerState.OPEN
        assert sub.consecutive_handler_failures == 7  # counter keeps climbing

    @pytest.mark.asyncio
    async def test_metric_failure_does_not_break_processing(self, domain):
        # An OTEL exporter that raises on the transition record must not unwind
        # process_batch (which would force a needless redelivery). The state
        # still transitions; the failure is swallowed.
        from protean.utils.telemetry import get_domain_metrics

        sub = _make_stream_subscription(domain, circuit_breaker_threshold=1)
        metrics = get_domain_metrics(domain)
        boom = Mock()
        boom.add = Mock(side_effect=RuntimeError("exporter down"))
        metrics.subscription_circuit_breaker_state = boom

        await sub.process_batch([_message("fail")], stream="test::user")

        assert sub.circuit_state == CircuitBreakerState.OPEN
        boom.add.assert_called_once()


# ---------------------------------------------------------------------------
# Trace emission (positive + negative)
# ---------------------------------------------------------------------------


class TestCircuitBreakerTraces:
    @pytest.mark.asyncio
    async def test_opened_emits_trace(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=2)

        await sub.process_batch(
            [_message("fail"), _message("fail")], stream="test::user"
        )

        assert "subscription.circuit_breaker.opened" in _circuit_emit_events(
            sub.engine.emitter
        )

    @pytest.mark.asyncio
    async def test_closed_emits_trace(self, domain):
        sub = _make_stream_subscription(domain)
        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        sub.circuit_opened_at = time.monotonic()

        await sub.process_batch([_message("ok")], stream="test::user")

        assert "subscription.circuit_breaker.closed" in _circuit_emit_events(
            sub.engine.emitter
        )

    @pytest.mark.asyncio
    async def test_half_open_emits_trace(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_reset_seconds=1)
        sub.circuit_state = CircuitBreakerState.OPEN
        sub.circuit_opened_at = time.monotonic() - 10

        await sub._circuit_permits_reads()

        assert "subscription.circuit_breaker.half_open" in _circuit_emit_events(
            sub.engine.emitter
        )

    @pytest.mark.asyncio
    async def test_no_trace_below_threshold(self, domain):
        sub = _make_stream_subscription(domain, circuit_breaker_threshold=5)

        await sub.process_batch([_message("fail")], stream="test::user")

        assert _circuit_emit_events(sub.engine.emitter) == []
