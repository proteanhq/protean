"""Tests for per-subscription OTEL metrics instrumentation.

Verifies that:
- ``StreamSubscription.process_batch()`` increments
  ``protean.subscription.messages_processed`` and records
  ``protean.subscription.processing_duration``.
- ``StreamSubscription._retry_message()`` increments
  ``protean.subscription.retries``.
- ``StreamSubscription.move_to_dlq()`` increments
  ``protean.subscription.dlq_routed``.
- ``BrokerSubscription`` has the same instrumentation.
- Engine observable gauges (``protean.engine.up``,
  ``protean.engine.uptime_seconds``, ``protean.engine.active_subscriptions``)
  report correct values.
- All metrics are no-op when OTEL is not configured.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.observatory.metrics import (
    _hand_rolled_metrics,
    _register_infrastructure_gauges,
    _scrape_cache,
)
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from protean.utils.telemetry import (
    _DOMAIN_METRICS_KEY,
    get_domain_metrics,
)

# ---------------------------------------------------------------------------
# Domain elements for testing
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


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        pass


class FailingEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        raise RuntimeError("Handler exploded")


class SucceedingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        pass


class FailingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        raise Exception("Subscriber failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing.

    Returns (span_exporter, metric_reader) for inspecting captured data.
    """
    resource = Resource.create({"service.name": domain.normalized_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter, metric_reader


def _get_metric(metric_reader, name: str):
    """Find a metric by name from the InMemoryMetricReader."""
    data = metric_reader.get_metrics_data()
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    return metric
    return None


def _get_metric_data_points(metric_reader, name: str) -> list:
    """Get all data points for a metric by name."""
    metric = _get_metric(metric_reader, name)
    if metric is None:
        return []
    return list(metric.data.data_points)


def _make_event_message(test_domain) -> Message:
    """Helper to create a valid event Message."""
    identifier = str(uuid4())
    user = User(id=identifier, email="test@example.com", name="Test")
    user.raise_(Registered(id=identifier, email="test@example.com", name="Test"))
    return Message.from_domain_object(user._events[-1])


def _make_stream_subscription(test_domain, handler_cls=UserEventHandler, **overrides):
    """Create a StreamSubscription on a real Engine for the handler."""
    engine = Engine(test_domain, test_mode=True)
    sub = StreamSubscription(
        engine=engine,
        stream_category="test::user",
        handler=handler_cls,
        messages_per_tick=10,
        blocking_timeout_ms=100,
        max_retries=overrides.pop("max_retries", 3),
        retry_delay_seconds=overrides.pop("retry_delay_seconds", 0),
        enable_dlq=overrides.pop("enable_dlq", True),
    )
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


async def _deliver_events(sub, count: int = 1) -> list:
    """Publish ``count`` events to the domain broker and read them back."""
    await sub.initialize()
    for _ in range(count):
        sub.broker.publish(
            sub.stream_category, _make_event_message(sub.engine.domain).to_dict()
        )
    batch = await sub.get_next_batch_of_messages()
    assert len(batch) == count
    return batch


def _make_broker_subscription(test_domain, subscriber_cls, **overrides):
    """Create an Engine and return the BrokerSubscription for the subscriber."""
    engine = Engine(test_domain, test_mode=True)
    sub = engine._broker_subscriptions[fqn(subscriber_cls)]
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


async def _deliver_payload(sub) -> list:
    """Publish one payload to the subscriber's broker stream and read it back."""
    sub.broker.publish(sub.stream_name, {"data": "test"})
    batch = await sub.get_next_batch_of_messages()
    assert len(batch) == 1
    return batch


# ---------------------------------------------------------------------------
# StreamSubscription metric tests
# ---------------------------------------------------------------------------


class TestStreamSubscriptionMessagesProcessed:
    """StreamSubscription.process_batch() increments
    ``protean.subscription.messages_processed`` and records
    ``protean.subscription.processing_duration`` on success and failure."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_successful_messages_accumulate_with_duration(
        self, test_domain, telemetry
    ):
        metric_reader = telemetry
        sub = _make_stream_subscription(test_domain, UserEventHandler)
        batch = await _deliver_events(sub, count=3)

        assert await sub.process_batch(batch, stream="test::user") == 3

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        ok_points = [p for p in points if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 3
        assert dict(ok_points[0].attributes)["subscription"] == "UserEventHandler"
        assert dict(ok_points[0].attributes)["stream"] == "test::user"

        durations = _get_metric_data_points(
            metric_reader, "protean.subscription.processing_duration"
        )
        assert len(durations) == 1
        assert durations[0].sum > 0
        assert durations[0].count == 3
        assert dict(durations[0].attributes)["subscription"] == "UserEventHandler"

    @pytest.mark.asyncio
    async def test_failure_increments_counter_with_error(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(test_domain, FailingEventHandler)
        batch = await _deliver_events(sub)

        await sub.process_batch(batch, stream="test::user")

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1


class TestStreamSubscriptionRetries:
    """StreamSubscription._retry_message() increments
    ``protean.subscription.retries``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_each_retry_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(
            test_domain,
            FailingEventHandler,
            retry_delay_seconds=0,
            max_retries=5,
        )
        batch = await _deliver_events(sub)

        await sub.process_batch(batch, stream="test::user")

        points = _get_metric_data_points(metric_reader, "protean.subscription.retries")
        assert len(points) == 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingEventHandler"

        # Process the same message again, as a re-delivery would.
        await sub.process_batch(batch, stream="test::user")

        points = _get_metric_data_points(metric_reader, "protean.subscription.retries")
        assert sum(p.value for p in points) == 2


class TestStreamSubscriptionDLQRouted:
    """StreamSubscription.move_to_dlq() increments
    ``protean.subscription.dlq_routed``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_dlq_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(
            test_domain,
            FailingEventHandler,
            retry_delay_seconds=0,
            max_retries=1,
            enable_dlq=True,
        )
        batch = await _deliver_events(sub)

        # First attempt: retry count 1 reaches max_retries 1, so the message
        # goes to the DLQ.
        await sub.process_batch(batch, stream="test::user")

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.dlq_routed"
        )
        assert len(points) >= 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingEventHandler"
        assert dict(points[0].attributes)["stream"] == "test::user"
        assert len(sub.broker.read(sub.dlq_stream, "dlq-check", 10)) == 1


# ---------------------------------------------------------------------------
# BrokerSubscription metric tests
# ---------------------------------------------------------------------------


class TestBrokerSubscriptionMessagesProcessed:
    """BrokerSubscription.process_batch() increments
    ``protean.subscription.messages_processed``, records
    ``protean.subscription.processing_duration`` and, on failure,
    ``protean.subscription.retries``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["message_processing"] = Processing.ASYNC.value
        test_domain.register(SucceedingSubscriber, stream="test_stream")
        test_domain.register(FailingSubscriber, stream="fail_stream")
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_success_increments_counter_and_records_duration(
        self, test_domain, telemetry
    ):
        metric_reader = telemetry
        sub = _make_broker_subscription(test_domain, SucceedingSubscriber)
        batch = await _deliver_payload(sub)

        assert await sub.process_batch(batch) == 1

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        ok_points = [p for p in points if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 1
        assert dict(ok_points[0].attributes)["subscription"] == "SucceedingSubscriber"

        durations = _get_metric_data_points(
            metric_reader, "protean.subscription.processing_duration"
        )
        assert len(durations) >= 1
        assert durations[0].sum > 0
        assert durations[0].count == 1
        assert dict(durations[0].attributes)["subscription"] == "SucceedingSubscriber"

    @pytest.mark.asyncio
    async def test_failure_increments_error_and_retry_counters(
        self, test_domain, telemetry
    ):
        metric_reader = telemetry
        sub = _make_broker_subscription(
            test_domain, FailingSubscriber, retry_delay_seconds=0, max_retries=3
        )
        batch = await _deliver_payload(sub)

        await sub.process_batch(batch)

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1

        retries = _get_metric_data_points(metric_reader, "protean.subscription.retries")
        assert len(retries) >= 1
        assert retries[0].value == 1
        assert dict(retries[0].attributes)["subscription"] == "FailingSubscriber"


class TestBrokerSubscriptionDLQRouted:
    """BrokerSubscription._move_to_dlq() increments
    ``protean.subscription.dlq_routed``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["message_processing"] = Processing.ASYNC.value
        test_domain.register(FailingSubscriber, stream="fail_stream")
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_dlq_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_broker_subscription(
            test_domain,
            FailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
            enable_dlq=True,
        )
        batch = await _deliver_payload(sub)

        # First failure: retry count reaches max_retries, so the message goes
        # to the DLQ.
        await sub.process_batch(batch)

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.dlq_routed"
        )
        assert len(points) >= 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingSubscriber"
        assert len(sub.broker.read(sub.dlq_stream, "dlq-check", 10)) == 1


# ---------------------------------------------------------------------------
# Engine observable gauge tests
# ---------------------------------------------------------------------------


class TestEngineObservableGauges:
    """Engine registers ``protean.engine.up``, ``protean.engine.uptime_seconds``,
    and ``protean.engine.active_subscriptions`` observable gauges."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    def test_running_engine_reports_up_uptime_and_subscriptions(
        self, test_domain, telemetry
    ):
        metric_reader = telemetry
        # Engine creation registers the gauges as a side effect
        engine = Engine(test_domain, test_mode=True)

        expected_count = len(engine._subscriptions) + len(engine._broker_subscriptions)
        assert expected_count > 0  # Ensure we have subscriptions to count

        up = _get_metric_data_points(metric_reader, "protean.engine.up")
        assert len(up) >= 1
        assert up[0].value == 1

        uptime = _get_metric_data_points(metric_reader, "protean.engine.uptime_seconds")
        assert len(uptime) >= 1
        assert uptime[0].value >= 0

        active = _get_metric_data_points(
            metric_reader, "protean.engine.active_subscriptions"
        )
        assert len(active) >= 1
        assert active[0].value == expected_count

    def test_engine_up_reports_zero_when_shutting_down(self, test_domain, telemetry):
        metric_reader = telemetry
        engine = Engine(test_domain, test_mode=True)
        engine.shutting_down = True

        points = _get_metric_data_points(metric_reader, "protean.engine.up")
        assert len(points) >= 1
        assert points[0].value == 0


# ---------------------------------------------------------------------------
# DomainMetrics instrument tests
# ---------------------------------------------------------------------------


class TestSubscriptionMetricsInDomainMetrics:
    """DomainMetrics contains the subscription instruments."""

    @pytest.fixture()
    def telemetry(self, test_domain):
        _, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    def test_subscription_counters_accept_attributes(self, test_domain, telemetry):
        metric_reader = telemetry
        metrics = get_domain_metrics(test_domain)
        attrs = {
            "subscription": "TestHandler",
            "handler": "TestHandler",
            "stream": "test::stream",
        }

        metrics.subscription_messages_processed.add(1, {**attrs, "status": "ok"})
        metrics.subscription_retries.add(1, attrs)
        metrics.subscription_dlq_routed.add(1, attrs)
        metrics.subscription_processing_duration.record(0.5, attrs)

        # Verify data points were recorded
        for name in [
            "protean.subscription.messages_processed",
            "protean.subscription.retries",
            "protean.subscription.dlq_routed",
            "protean.subscription.processing_duration",
        ]:
            points = _get_metric_data_points(metric_reader, name)
            assert len(points) >= 1, f"No data points for {name}"


# ---------------------------------------------------------------------------
# No-op behavior tests
# ---------------------------------------------------------------------------


class TestNoOpSubscriptionMetrics:
    """Subscription metrics are no-op when telemetry is not configured."""

    def test_noop_subscription_counters(self, test_domain):
        """DomainMetrics subscription instruments work without OTel configured."""
        metrics = get_domain_metrics(test_domain)
        attrs = {
            "subscription": "Test",
            "handler": "Test",
            "stream": "test",
        }

        # Should not raise
        metrics.subscription_messages_processed.add(1, {**attrs, "status": "ok"})
        metrics.subscription_retries.add(1, attrs)
        metrics.subscription_dlq_routed.add(1, attrs)
        metrics.subscription_processing_duration.record(0.5, attrs)


# ---------------------------------------------------------------------------
# Subscription lag-seconds gauge (infrastructure gauge + hand-rolled fallback)
# ---------------------------------------------------------------------------


class LagProjection(BaseProjection):
    user_id = Identifier(identifier=True)
    name = String()


class LagProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        pass


def _seed_lagging(test_domain, seconds_behind: int = 120) -> None:
    """Write events and a position that trails head by a fixed wall-clock gap.

    The position message carries a timestamp ``seconds_behind`` in the past and
    a position below head, so the event-store subscription reports a positive
    ``lag`` and a positive ``lag_seconds``.
    """
    with test_domain.domain_context():
        store = test_domain.event_store.store
        category = LagProjector.meta_.stream_categories[0]
        for i in range(3):
            store._write(f"{category}-{i}", "Registered", {"user_id": str(i)})
        old = (datetime.now(UTC) - timedelta(seconds=seconds_behind)).isoformat()
        store._write(
            f"position-{fqn(LagProjector)}-{category}",
            "Read",
            {"position": 0},
            metadata={"headers": {"time": old}},
        )


class TestSubscriptionLagSecondsGauge:
    """``protean.subscription.lag_seconds`` emits through both metric paths."""

    @pytest.fixture(autouse=True)
    def _elements(self, test_domain):
        test_domain.register(User)
        test_domain.register(Registered, part_of=User)
        test_domain.register(LagProjection)
        test_domain.register(
            LagProjector, projector_for=LagProjection, aggregates=[User]
        )
        test_domain.init(traverse=False)

    @pytest.fixture(autouse=True)
    def _clear_scrape_cache(self):
        _scrape_cache.clear()
        yield
        _scrape_cache.clear()

    def test_gauge_emits_seconds_behind_on_scrape(self, test_domain):
        """The OTel gauge is registered and reports the projector's seconds behind.

        The real store stamps the position record at write time, so seconds-behind
        is measured against the collection clock. Advancing that clock 300s past
        the write makes the reported value a controlled, non-trivial number rather
        than the sub-millisecond gap of a just-written record.
        """
        _seed_lagging(test_domain)
        _, metric_reader = _init_telemetry_in_memory(test_domain)

        _register_infrastructure_gauges([test_domain])

        future = datetime.now(UTC) + timedelta(seconds=300)
        with patch.object(test_domain.clock, "now", return_value=future):
            metric = _get_metric(metric_reader, "protean.subscription.lag_seconds")
            assert metric is not None
            # The gauge is registered with an explicit unit so scrapers label it
            # as seconds; that is the reason it gets its own registration.
            assert metric.unit == "s"

            points = list(metric.data.data_points)
            point = next(
                p for p in points if p.attributes.get("handler") == "LagProjector"
            )
        # The store stamps the position at write time (~now), and the clock is
        # advanced 300s past it, so the elapsed-time branch reports ~300s (not the
        # caught-up 0.0 short-circuit).
        assert point.value == pytest.approx(300, abs=30)

    def test_hand_rolled_fallback_emits_seconds_behind(self, test_domain):
        """The hand-rolled text carries the seconds-behind value for the projector."""
        _seed_lagging(test_domain)

        # The store stamps the position at write time; advance the clock 300s past
        # it so the emitted value is a controlled, non-trivial number rather than
        # the sub-millisecond gap of a just-written record.
        future = datetime.now(UTC) + timedelta(seconds=300)
        with patch.object(test_domain.clock, "now", return_value=future):
            text = _hand_rolled_metrics([test_domain])

        assert "# HELP protean_subscription_lag_seconds" in text
        assert "# TYPE protean_subscription_lag_seconds gauge" in text
        assert "protean_subscription_lag_seconds{" in text
        assert 'handler="LagProjector"' in text

        # The emitted value is the real elapsed gap, not a placeholder.
        line = next(
            ln
            for ln in text.splitlines()
            if ln.startswith("protean_subscription_lag_seconds{")
            and 'handler="LagProjector"' in ln
        )
        value = float(line.rsplit(" ", 1)[1])
        assert value == pytest.approx(300, abs=30)

    def test_gauge_skips_seconds_when_none(self, test_domain):
        """A status whose ``lag_seconds`` is None emits no OTel data point.

        The count-based lag path already guards this; the seconds gauge must not
        report a data point (which would read as ``0.0``) when the value is
        unavailable. A projector that has never written a position trails head
        by a real message count, but has no timestamp to measure seconds from.
        """
        with test_domain.domain_context():
            store = test_domain.event_store.store
            category = LagProjector.meta_.stream_categories[0]
            for i in range(3):
                store._write(f"{category}-{i}", "Registered", {"user_id": str(i)})
        _, metric_reader = _init_telemetry_in_memory(test_domain)

        _register_infrastructure_gauges([test_domain])
        points = _get_metric_data_points(
            metric_reader, "protean.subscription.lag_seconds"
        )
        lag_points = _get_metric_data_points(
            metric_reader, "protean.subscription.consumer_lag"
        )

        assert not any(p.attributes.get("handler") == "LagProjector" for p in points)
        # The count-based lag still reports, proving the status was collected and
        # only the None seconds were skipped.
        assert any(
            p.attributes.get("handler") == "LagProjector" and p.value > 0
            for p in lag_points
        )
