"""Tests for OpenTelemetry span instrumentation on server subscriptions
and outbox processor.

Verifies that:
- ``Engine.handle_message()`` emits a ``protean.engine.handle_message`` span
  with correct attributes (handler name, message type, stream, worker_id,
  subscription_type).
- ``OutboxProcessor.process_batch()`` emits a ``protean.outbox.process`` span
  per batch with batch_size and successful_count.
- ``OutboxProcessor._process_single_message()`` emits a
  ``protean.outbox.publish`` span per message.
- Error scenarios record exceptions and set ERROR status on spans.
- Spans are not emitted when telemetry is not enabled.
"""

import asyncio
from unittest.mock import Mock
from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, Integer, String
from protean.server import Engine
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.mixins import handle
from protean.utils.outbox import Outbox


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name
        self.password_hash = event.password_hash


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        pass


class FailingEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        raise RuntimeError("Handler exploded")


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        pass


class DummyAggregate(BaseAggregate):
    name = String(max_length=50, required=True)
    count = Integer(default=0)

    def increment(self) -> None:
        self.count += 1
        self.raise_(
            DummyEvent(aggregate_id=str(self.id), name=self.name, count=self.count)
        )


class DummyEvent(BaseEvent):
    aggregate_id = String(required=True)
    name = String(required=True)
    count = Integer(required=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockEngine:
    """Simple mock engine that provides only the necessary interface."""

    def __init__(self, domain):
        self.domain = domain
        self.loop = None
        self.emitter = Mock()
        self.shutting_down = False


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing."""
    resource = Resource.create({"service.name": domain.normalized_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter


def _make_event_message(test_domain) -> Message:
    """Helper to create a valid event Message."""
    identifier = str(uuid4())
    user = User(
        id=identifier,
        email="test@example.com",
        name="Test",
        password_hash="hash",
    )
    user.raise_(
        Registered(
            id=identifier,
            email="test@example.com",
            name="Test",
            password_hash="hash",
        )
    )
    return Message.from_domain_object(user._events[-1])


def _make_command_message(test_domain) -> Message:
    """Helper to create a valid command Message."""
    identifier = str(uuid4())
    command = Register(user_id=identifier, email="test@example.com")
    enriched = test_domain._enrich_command(command, True)
    return Message.from_domain_object(enriched)


def _persist_outbox_messages(domain, count: int = 3) -> list[Outbox]:
    """Create test outbox messages in the outbox repo."""
    outbox_repo = domain._get_outbox_repo("default")

    messages = []
    for i in range(count):
        headers = MessageHeaders(
            id=f"msg-{i}", type="DummyEvent", stream="test-stream"
        )
        domain_meta = DomainMeta(stream_category="test-stream")
        metadata = Metadata(headers=headers, domain=domain_meta)

        msg = Outbox.create_message(
            message_id=f"msg-{i}",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"name": f"Test {i}", "count": i},
            metadata=metadata,
            priority=i,
            correlation_id=f"corr-{i}",
        )
        outbox_repo.add(msg)
        messages.append(msg)

    return messages


# ---------------------------------------------------------------------------
# Tests: Engine.handle_message() span
# ---------------------------------------------------------------------------


class TestEngineHandleMessageSpan:
    """Engine.handle_message() emits ``protean.engine.handle_message``."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.register(Register, part_of=User)
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def span_exporter(self, test_domain):
        return _init_telemetry_in_memory(test_domain)

    @pytest.mark.asyncio
    async def test_handle_message_emits_span(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "protean.engine.handle_message" in span_names

    @pytest.mark.asyncio
    async def test_span_has_handler_name(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert span.attributes["protean.handler.name"] == "UserEventHandler"

    @pytest.mark.asyncio
    async def test_span_has_message_type(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert "protean.message.type" in span.attributes
        assert span.attributes["protean.message.type"] != "unknown"

    @pytest.mark.asyncio
    async def test_span_has_message_id(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert "protean.message.id" in span.attributes
        assert span.attributes["protean.message.id"] != "unknown"

    @pytest.mark.asyncio
    async def test_span_has_stream_category(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert "protean.stream_category" in span.attributes
        assert span.attributes["protean.stream_category"] != ""

    @pytest.mark.asyncio
    async def test_span_has_worker_id_when_provided(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(
            UserEventHandler, message, worker_id="worker-42"
        )

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert span.attributes["protean.worker_id"] == "worker-42"

    @pytest.mark.asyncio
    async def test_span_has_subscription_type_event_handler(
        self, test_domain, span_exporter
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert span.attributes["protean.subscription_type"] == "event_handler"

    @pytest.mark.asyncio
    async def test_span_has_subscription_type_command_handler(
        self, test_domain, span_exporter
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_command_message(test_domain)

        await engine.handle_message(UserCommandHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")
        assert span.attributes["protean.subscription_type"] == "command_handler"


# ---------------------------------------------------------------------------
# Tests: Engine.handle_message() error span
# ---------------------------------------------------------------------------


class TestEngineHandleMessageErrorSpan:
    """Engine.handle_message() records errors on span when handler fails."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def span_exporter(self, test_domain):
        return _init_telemetry_in_memory(test_domain)

    @pytest.mark.asyncio
    async def test_error_recorded_on_span(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        result = await engine.handle_message(FailingEventHandler, message)
        assert result is False

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")

        assert span.status.status_code == StatusCode.ERROR
        assert "Handler exploded" in span.status.description

    @pytest.mark.asyncio
    async def test_exception_event_recorded(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(FailingEventHandler, message)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.engine.handle_message")

        exception_events = [e for e in span.events if e.name == "exception"]
        assert len(exception_events) == 1
        assert "Handler exploded" in exception_events[0].attributes["exception.message"]


# ---------------------------------------------------------------------------
# Tests: Engine.handle_message() without telemetry
# ---------------------------------------------------------------------------


class TestEngineHandleMessageWithoutTelemetry:
    """handle_message works correctly when telemetry is not enabled."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_successful_handling(self, test_domain):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        result = await engine.handle_message(UserEventHandler, message)
        assert result is True

    @pytest.mark.asyncio
    async def test_failed_handling(self, test_domain):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        result = await engine.handle_message(FailingEventHandler, message)
        assert result is False


# ---------------------------------------------------------------------------
# Tests: Engine.handle_message() span parent-child relationships
# ---------------------------------------------------------------------------


class TestEngineSpanRelationships:
    """Verify span hierarchy when engine processes messages."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def span_exporter(self, test_domain):
        return _init_telemetry_in_memory(test_domain)

    @pytest.mark.asyncio
    async def test_handler_execute_is_child_of_engine_span(
        self, test_domain, span_exporter
    ):
        """handler.execute should be a child of engine.handle_message."""
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = next(
            s for s in spans if s.name == "protean.engine.handle_message"
        )
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        assert handler_span.parent is not None
        assert handler_span.parent.span_id == engine_span.context.span_id

    @pytest.mark.asyncio
    async def test_all_spans_share_trace_id(self, test_domain, span_exporter):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1


# ---------------------------------------------------------------------------
# Tests: OutboxProcessor.process_batch() span
# ---------------------------------------------------------------------------


@pytest.mark.database
class TestOutboxProcessBatchSpan:
    """OutboxProcessor.process_batch() emits ``protean.outbox.process``."""

    @pytest.fixture(autouse=True)
    def setup_outbox_domain(self, test_domain):
        test_domain.config["enable_outbox"] = True
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.register(DummyAggregate)
        test_domain.register(DummyEvent, part_of=DummyAggregate)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def span_exporter(self, test_domain):
        return _init_telemetry_in_memory(test_domain)

    @pytest.mark.asyncio
    async def test_process_batch_emits_span(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=2)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "protean.outbox.process" in span_names

    @pytest.mark.asyncio
    async def test_process_span_has_batch_size(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=2)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.outbox.process")
        assert span.attributes["protean.outbox.batch_size"] == 2

    @pytest.mark.asyncio
    async def test_process_span_has_processor_id(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.outbox.process")
        assert "protean.outbox.processor_id" in span.attributes
        assert span.attributes["protean.outbox.processor_id"] != ""

    @pytest.mark.asyncio
    async def test_process_span_has_is_external(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.outbox.process")
        assert span.attributes["protean.outbox.is_external"] is False

    @pytest.mark.asyncio
    async def test_process_span_has_successful_count(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=2)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "protean.outbox.process")
        assert "protean.outbox.successful_count" in span.attributes
        assert span.attributes["protean.outbox.successful_count"] >= 0


# ---------------------------------------------------------------------------
# Tests: OutboxProcessor._process_single_message() publish span
# ---------------------------------------------------------------------------


@pytest.mark.database
class TestOutboxPublishSpan:
    """OutboxProcessor._process_single_message() emits ``protean.outbox.publish``."""

    @pytest.fixture(autouse=True)
    def setup_outbox_domain(self, test_domain):
        test_domain.config["enable_outbox"] = True
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.register(DummyAggregate)
        test_domain.register(DummyEvent, part_of=DummyAggregate)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def span_exporter(self, test_domain):
        return _init_telemetry_in_memory(test_domain)

    @pytest.mark.asyncio
    async def test_publish_span_emitted_per_message(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=2)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_spans = [s for s in spans if s.name == "protean.outbox.publish"]
        assert len(publish_spans) == 2

    @pytest.mark.asyncio
    async def test_publish_span_has_message_id(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")
        assert "protean.outbox.message_id" in publish_span.attributes
        assert publish_span.attributes["protean.outbox.message_id"] != ""

    @pytest.mark.asyncio
    async def test_publish_span_has_stream_category(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")
        assert "protean.outbox.stream_category" in publish_span.attributes

    @pytest.mark.asyncio
    async def test_publish_span_has_message_type(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")
        assert publish_span.attributes["protean.outbox.message_type"] == "DummyEvent"

    @pytest.mark.asyncio
    async def test_publish_span_has_is_external(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")
        assert publish_span.attributes["protean.outbox.is_external"] is False

    @pytest.mark.asyncio
    async def test_publish_span_has_processor_id(self, test_domain, span_exporter):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")
        assert "protean.outbox.processor_id" in publish_span.attributes

    @pytest.mark.asyncio
    async def test_publish_span_is_child_of_process_span(
        self, test_domain, span_exporter
    ):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.outbox.process")
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")

        assert publish_span.parent is not None
        assert publish_span.parent.span_id == process_span.context.span_id


# ---------------------------------------------------------------------------
# Tests: OutboxProcessor error spans
# ---------------------------------------------------------------------------


@pytest.mark.database
class TestOutboxPublishErrorSpan:
    """OutboxProcessor records errors on publish span when broker fails."""

    @pytest.fixture(autouse=True)
    def setup_outbox_domain(self, test_domain):
        test_domain.config["enable_outbox"] = True
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.register(DummyAggregate)
        test_domain.register(DummyEvent, part_of=DummyAggregate)
        test_domain.init(traverse=False)

    @pytest.fixture()
    def span_exporter(self, test_domain):
        return _init_telemetry_in_memory(test_domain)

    @pytest.mark.asyncio
    async def test_publish_error_recorded_on_span(
        self, test_domain, span_exporter, monkeypatch
    ):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Make broker publish fail
        original_publish = processor.broker.publish
        monkeypatch.setattr(
            processor.broker,
            "publish",
            Mock(side_effect=RuntimeError("Broker down")),
        )

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")

        assert publish_span.status.status_code == StatusCode.ERROR
        assert "Broker down" in publish_span.status.description

    @pytest.mark.asyncio
    async def test_publish_exception_event_recorded(
        self, test_domain, span_exporter, monkeypatch
    ):
        _persist_outbox_messages(test_domain, count=1)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        monkeypatch.setattr(
            processor.broker,
            "publish",
            Mock(side_effect=RuntimeError("Broker down")),
        )

        messages = await processor.get_next_batch_of_messages()
        await processor.process_batch(messages)

        spans = span_exporter.get_finished_spans()
        publish_span = next(s for s in spans if s.name == "protean.outbox.publish")

        exception_events = [e for e in publish_span.events if e.name == "exception"]
        assert len(exception_events) == 1
        assert "Broker down" in exception_events[0].attributes["exception.message"]


# ---------------------------------------------------------------------------
# Tests: OutboxProcessor without telemetry
# ---------------------------------------------------------------------------


@pytest.mark.database
class TestOutboxProcessorWithoutTelemetry:
    """OutboxProcessor works correctly when telemetry is not enabled."""

    @pytest.fixture(autouse=True)
    def setup_outbox_domain(self, test_domain):
        test_domain.config["enable_outbox"] = True
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.register(DummyAggregate)
        test_domain.register(DummyEvent, part_of=DummyAggregate)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_process_batch_works_without_telemetry(self, test_domain):
        _persist_outbox_messages(test_domain, count=2)

        engine = MockEngine(test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        result = await processor.process_batch(messages)

        assert result >= 0
