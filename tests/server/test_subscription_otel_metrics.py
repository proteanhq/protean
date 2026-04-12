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

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, Mock
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
from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from protean.utils.telemetry import (
    DomainMetrics,
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
    user.raise_(
        Registered(id=identifier, email="test@example.com", name="Test")
    )
    return Message.from_domain_object(user._events[-1])


class MockEngine:
    """Minimal engine mock for subscription tests.

    Delegates ``handle_message`` to the real Engine implementation
    so that handler dispatch works correctly with real domain elements.
    """

    def __init__(self, domain):
        self.domain = domain
        self.loop = asyncio.new_event_loop()
        self.emitter = Mock()
        self.shutting_down = False
        # Create a real engine for message handling
        self._real_engine = Engine(domain, test_mode=True)

    async def handle_message(self, handler_cls, message, worker_id=None):
        return await self._real_engine.handle_message(
            handler_cls, message, worker_id=worker_id
        )


def _make_stream_subscription(test_domain, handler_cls=UserEventHandler, **overrides):
    """Create a StreamSubscription with a mock engine for the handler."""
    engine = MockEngine(test_domain)
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
    # Set a mock broker so ack/nack/publish calls work
    sub.broker = MagicMock()
    sub.broker.ack = MagicMock(return_value=True)
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


def _make_broker_subscription(test_domain, subscriber_cls, **overrides):
    """Create an Engine and return the BrokerSubscription for the subscriber."""
    engine = Engine(test_domain, test_mode=True)
    sub = engine._broker_subscriptions[fqn(subscriber_cls)]
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


# ---------------------------------------------------------------------------
# StreamSubscription metric tests
# ---------------------------------------------------------------------------


class TestStreamSubscriptionMessagesProcessed:
    """StreamSubscription.process_batch() increments
    ``protean.subscription.messages_processed`` on success and failure."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_success_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(test_domain, UserEventHandler)

        message = _make_event_message(test_domain)
        serialized = message.to_dict()

        # Mock the broker ack
        sub.broker = MagicMock()
        sub.broker.ack = MagicMock(return_value=True)

        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        ok_points = [p for p in points if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 1
        assert dict(ok_points[0].attributes)["subscription"] == "UserEventHandler"
        assert dict(ok_points[0].attributes)["stream"] == "test::user"

    @pytest.mark.asyncio
    async def test_failure_increments_counter_with_error(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(test_domain, FailingEventHandler)

        message = _make_event_message(test_domain)
        serialized = message.to_dict()

        sub.broker = MagicMock()
        sub.broker.nack = MagicMock(return_value=True)
        sub.retry_delay_seconds = 0

        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1

    @pytest.mark.asyncio
    async def test_multiple_messages_accumulate(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(test_domain, UserEventHandler)

        sub.broker = MagicMock()
        sub.broker.ack = MagicMock(return_value=True)

        messages = []
        for i in range(3):
            msg = _make_event_message(test_domain)
            messages.append((f"msg-{i}", msg.to_dict()))

        await sub.process_batch(messages, stream="test::user")

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        ok_points = [p for p in points if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 3


class TestStreamSubscriptionProcessingDuration:
    """StreamSubscription.process_batch() records
    ``protean.subscription.processing_duration`` histogram."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_records_duration(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(test_domain, UserEventHandler)

        message = _make_event_message(test_domain)
        serialized = message.to_dict()

        sub.broker = MagicMock()
        sub.broker.ack = MagicMock(return_value=True)

        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.processing_duration"
        )
        assert len(points) >= 1
        assert points[0].sum > 0
        assert points[0].count == 1
        assert dict(points[0].attributes)["subscription"] == "UserEventHandler"


class TestStreamSubscriptionRetries:
    """StreamSubscription._retry_message() increments
    ``protean.subscription.retries``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_retry_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(
            test_domain,
            FailingEventHandler,
            retry_delay_seconds=0,
            max_retries=3,
        )

        message = _make_event_message(test_domain)
        serialized = message.to_dict()

        sub.broker = MagicMock()
        sub.broker.nack = MagicMock(return_value=True)

        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.retries"
        )
        assert len(points) >= 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingEventHandler"

    @pytest.mark.asyncio
    async def test_multiple_retries_accumulate(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_stream_subscription(
            test_domain,
            FailingEventHandler,
            retry_delay_seconds=0,
            max_retries=5,
        )

        message = _make_event_message(test_domain)
        serialized = message.to_dict()

        sub.broker = MagicMock()
        sub.broker.nack = MagicMock(return_value=True)

        # Process the same message twice (simulating re-delivery)
        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )
        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.retries"
        )
        assert len(points) >= 1
        total = sum(p.value for p in points)
        assert total == 2


class TestStreamSubscriptionDLQRouted:
    """StreamSubscription.move_to_dlq() increments
    ``protean.subscription.dlq_routed``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
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

        message = _make_event_message(test_domain)
        serialized = message.to_dict()

        sub.broker = MagicMock()
        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()

        # First attempt → retry (retry_count 1 >= max_retries 1 → DLQ)
        await sub.process_batch(
            [("msg-1", serialized)], stream="test::user"
        )

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.dlq_routed"
        )
        assert len(points) >= 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingEventHandler"
        assert dict(points[0].attributes)["stream"] == "test::user"


# ---------------------------------------------------------------------------
# BrokerSubscription metric tests
# ---------------------------------------------------------------------------


class TestBrokerSubscriptionMessagesProcessed:
    """BrokerSubscription.process_batch() increments
    ``protean.subscription.messages_processed``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["message_processing"] = Processing.ASYNC.value
        test_domain.register(SucceedingSubscriber, stream="test_stream")
        test_domain.register(FailingSubscriber, stream="fail_stream")
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_success_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_broker_subscription(test_domain, SucceedingSubscriber)

        sub.broker.ack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=True)

        await sub.process_batch([("msg-1", {"data": "test"})])

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        ok_points = [p for p in points if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 1
        assert (
            dict(ok_points[0].attributes)["subscription"] == "SucceedingSubscriber"
        )

    @pytest.mark.asyncio
    async def test_failure_increments_counter_with_error(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_broker_subscription(
            test_domain, FailingSubscriber, retry_delay_seconds=0
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        await sub.process_batch([("msg-1", {"data": "test"})])

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.messages_processed"
        )
        assert len(points) >= 1
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1


class TestBrokerSubscriptionProcessingDuration:
    """BrokerSubscription.process_batch() records
    ``protean.subscription.processing_duration``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["message_processing"] = Processing.ASYNC.value
        test_domain.register(SucceedingSubscriber, stream="test_stream")
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_records_duration(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_broker_subscription(test_domain, SucceedingSubscriber)

        sub.broker.ack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=True)

        await sub.process_batch([("msg-1", {"data": "test"})])

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.processing_duration"
        )
        assert len(points) >= 1
        assert points[0].sum > 0
        assert points[0].count == 1
        assert (
            dict(points[0].attributes)["subscription"] == "SucceedingSubscriber"
        )


class TestBrokerSubscriptionRetries:
    """BrokerSubscription._retry_message() increments
    ``protean.subscription.retries``."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["message_processing"] = Processing.ASYNC.value
        test_domain.register(FailingSubscriber, stream="fail_stream")
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    @pytest.mark.asyncio
    async def test_retry_increments_counter(self, test_domain, telemetry):
        metric_reader = telemetry
        sub = _make_broker_subscription(
            test_domain, FailingSubscriber, retry_delay_seconds=0, max_retries=3
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        await sub.process_batch([("msg-1", {"data": "test"})])

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.retries"
        )
        assert len(points) >= 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingSubscriber"


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
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
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

        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        # First failure → retry count reaches max_retries → DLQ
        await sub.process_batch([("msg-1", {"data": "test"})])

        points = _get_metric_data_points(
            metric_reader, "protean.subscription.dlq_routed"
        )
        assert len(points) >= 1
        assert points[0].value == 1
        assert dict(points[0].attributes)["subscription"] == "FailingSubscriber"


# ---------------------------------------------------------------------------
# Engine observable gauge tests
# ---------------------------------------------------------------------------


class TestEngineObservableGauges:
    """Engine registers ``protean.engine.up``, ``protean.engine.uptime_seconds``,
    and ``protean.engine.active_subscriptions`` observable gauges."""

    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    def test_engine_up_reports_one_when_running(self, test_domain, telemetry):
        metric_reader = telemetry
        engine = Engine(test_domain, test_mode=True)

        points = _get_metric_data_points(metric_reader, "protean.engine.up")
        assert len(points) >= 1
        assert points[0].value == 1

    def test_engine_up_reports_zero_when_shutting_down(self, test_domain, telemetry):
        metric_reader = telemetry
        engine = Engine(test_domain, test_mode=True)
        engine.shutting_down = True

        points = _get_metric_data_points(metric_reader, "protean.engine.up")
        assert len(points) >= 1
        assert points[0].value == 0

    def test_engine_uptime_reports_positive_value(self, test_domain, telemetry):
        metric_reader = telemetry
        engine = Engine(test_domain, test_mode=True)

        points = _get_metric_data_points(
            metric_reader, "protean.engine.uptime_seconds"
        )
        assert len(points) >= 1
        assert points[0].value >= 0

    def test_engine_active_subscriptions_counts_correctly(
        self, test_domain, telemetry
    ):
        metric_reader = telemetry
        engine = Engine(test_domain, test_mode=True)

        expected_count = len(engine._subscriptions) + len(
            engine._broker_subscriptions
        )
        assert expected_count > 0  # Ensure we have subscriptions to count

        points = _get_metric_data_points(
            metric_reader, "protean.engine.active_subscriptions"
        )
        assert len(points) >= 1
        assert points[0].value == expected_count


# ---------------------------------------------------------------------------
# DomainMetrics instrument existence tests
# ---------------------------------------------------------------------------


class TestSubscriptionMetricsInDomainMetrics:
    """DomainMetrics contains the new subscription instruments."""

    @pytest.fixture()
    def telemetry(self, test_domain):
        span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
        yield metric_reader
        if hasattr(test_domain, _DOMAIN_METRICS_KEY):
            delattr(test_domain, _DOMAIN_METRICS_KEY)

    def test_subscription_instruments_exist(self, test_domain, telemetry):
        metrics = get_domain_metrics(test_domain)
        assert hasattr(metrics, "subscription_messages_processed")
        assert hasattr(metrics, "subscription_dlq_routed")
        assert hasattr(metrics, "subscription_retries")
        assert hasattr(metrics, "subscription_processing_duration")

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
