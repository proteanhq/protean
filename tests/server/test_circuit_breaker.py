"""Tests for the per-subscription circuit breaker.

A ``StreamSubscription`` carries an in-memory circuit breaker that counts
consecutive handler-outcome failures and, once a threshold is crossed, pauses
reads (state ``OPEN``) so a struggling downstream is not hammered. After a reset
window it allows a single probe (``HALF_OPEN``); the probe's outcome closes the
breaker or re-opens it.

These tests cover:
- Opening at the threshold, and the read gate pausing reads while OPEN.
- The counter resetting on an intervening success (breaker does NOT open).
- The HALF_OPEN probe: single-message reads, closing on success, re-opening on
  failure with a restarted timer.
- Deserialization failures NOT counting as handler failures.
- Config resolution through the 7-level hierarchy plus round-trips.
- Validation of the two config keys.
- OTEL metric and trace emission on transitions, with matching negative cases.
"""

import asyncio
import time
from unittest.mock import MagicMock, Mock
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
