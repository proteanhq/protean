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
        headers = MessageHeaders(id=f"msg-{i}", type="DummyEvent", stream="test-stream")
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


def _persist_outbox_messages_uniform(
    domain, count: int = 2, causation_id: str | None = None
) -> list[Outbox]:
    """Create outbox messages sharing the same correlation/causation IDs."""
    outbox_repo = domain._get_outbox_repo("default")

    messages = []
    for i in range(count):
        headers = MessageHeaders(
            id=f"msg-uniform-{i}", type="DummyEvent", stream="test-stream"
        )
        domain_meta = DomainMeta(stream_category="test-stream")
        metadata = Metadata(headers=headers, domain=domain_meta)

        msg = Outbox.create_message(
            message_id=f"msg-uniform-{i}",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"name": f"Test {i}", "count": i},
            metadata=metadata,
            priority=0,
            correlation_id="shared-corr-id",
            causation_id=causation_id,
        )
        outbox_repo.add(msg)
        messages.append(msg)

    return messages


# ---------------------------------------------------------------------------
# Tests: Engine.handle_message() span
# ---------------------------------------------------------------------------


def _engine_span(span_exporter):
    return next(
        s
        for s in span_exporter.get_finished_spans()
        if s.name == "protean.engine.handle_message"
    )


class TestEngineHandleMessageSpan:
    """Engine.handle_message() emits ``protean.engine.handle_message``."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, event_sourced=True)
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
    async def test_span_carries_event_handler_attributes(
        self, test_domain, span_exporter
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message, worker_id="worker-42")

        span = _engine_span(span_exporter)
        assert span.attributes["protean.handler.name"] == "UserEventHandler"
        assert span.attributes["protean.message.type"] != "unknown"
        assert span.attributes["protean.message.id"] != "unknown"
        assert span.attributes["protean.stream_category"] != ""
        assert span.attributes["protean.worker_id"] == "worker-42"
        assert span.attributes["protean.subscription_type"] == "event_handler"

    @pytest.mark.asyncio
    async def test_span_has_subscription_type_command_handler(
        self, test_domain, span_exporter
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_command_message(test_domain)

        await engine.handle_message(UserCommandHandler, message)

        span = _engine_span(span_exporter)
        assert span.attributes["protean.subscription_type"] == "command_handler"

    @pytest.mark.asyncio
    async def test_handler_execute_is_child_of_engine_span(
        self, test_domain, span_exporter
    ):
        """handler.execute is a child of engine.handle_message, in one trace."""
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        await engine.handle_message(UserEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = _engine_span(span_exporter)
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        assert handler_span.parent is not None
        assert handler_span.parent.span_id == engine_span.context.span_id
        assert len({s.context.trace_id for s in spans}) == 1

    @pytest.mark.asyncio
    async def test_error_and_exception_event_recorded_on_span(
        self, test_domain, span_exporter
    ):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        result = await engine.handle_message(FailingEventHandler, message)
        assert result is False

        span = _engine_span(span_exporter)
        assert span.status.status_code == StatusCode.ERROR
        assert "Handler exploded" in span.status.description
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
        test_domain.register(User, event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler_cls, expected",
        [(UserEventHandler, True), (FailingEventHandler, False)],
    )
    async def test_handling_result(self, test_domain, handler_cls, expected):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        result = await engine.handle_message(handler_cls, message)
        assert result is expected


# ---------------------------------------------------------------------------
# Tests: OutboxProcessor spans
# ---------------------------------------------------------------------------


@pytest.fixture()
def outbox_domain(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.register(DummyAggregate)
    test_domain.register(DummyEvent, part_of=DummyAggregate)
    test_domain.init(traverse=False)
    return test_domain


async def _new_processor(domain) -> OutboxProcessor:
    engine = Engine(domain=domain, test_mode=True)
    processor = OutboxProcessor(engine, "default", "default")
    await processor.initialize()
    return processor


async def _process_one_batch(processor: OutboxProcessor) -> int:
    messages = await processor.get_next_batch_of_messages()
    return await processor.process_batch(messages)


def _outbox_spans(span_exporter, name):
    return [s for s in span_exporter.get_finished_spans() if s.name == name]


@pytest.mark.database
class TestOutboxProcessBatchSpan:
    """OutboxProcessor.process_batch() emits ``protean.outbox.process``."""

    @pytest.fixture()
    def span_exporter(self, outbox_domain):
        return _init_telemetry_in_memory(outbox_domain)

    @pytest.mark.asyncio
    async def test_process_span_attributes_with_mixed_correlation_ids(
        self, outbox_domain, span_exporter
    ):
        """Batch span omits correlation_id when messages have different ones."""
        _persist_outbox_messages(outbox_domain, count=2)

        await _process_one_batch(await _new_processor(outbox_domain))

        (span,) = _outbox_spans(span_exporter, "protean.outbox.process")
        assert span.attributes["protean.outbox.batch_size"] == 2
        assert span.attributes["protean.outbox.processor_id"] != ""
        assert span.attributes["protean.outbox.is_external"] is False
        assert span.attributes["protean.outbox.successful_count"] == 2
        assert "protean.correlation_id" not in span.attributes

    @pytest.mark.asyncio
    async def test_process_span_has_uniform_correlation_id(
        self, outbox_domain, span_exporter
    ):
        """Batch span sets correlation_id when all messages share the same one."""
        _persist_outbox_messages_uniform(outbox_domain, count=2)

        await _process_one_batch(await _new_processor(outbox_domain))

        (span,) = _outbox_spans(span_exporter, "protean.outbox.process")
        assert span.attributes["protean.correlation_id"] == "shared-corr-id"

    @pytest.mark.asyncio
    async def test_process_span_has_uniform_causation_id(
        self, outbox_domain, span_exporter
    ):
        """Batch span sets causation_id when all messages share the same one."""
        _persist_outbox_messages_uniform(
            outbox_domain, count=2, causation_id="shared-cause-id"
        )

        await _process_one_batch(await _new_processor(outbox_domain))

        (span,) = _outbox_spans(span_exporter, "protean.outbox.process")
        assert span.attributes["protean.causation_id"] == "shared-cause-id"


@pytest.mark.database
class TestOutboxPublishSpan:
    """OutboxProcessor._process_single_message() emits ``protean.outbox.publish``."""

    @pytest.fixture()
    def span_exporter(self, outbox_domain):
        return _init_telemetry_in_memory(outbox_domain)

    @pytest.mark.asyncio
    async def test_publish_span_emitted_per_message(self, outbox_domain, span_exporter):
        _persist_outbox_messages(outbox_domain, count=2)

        await _process_one_batch(await _new_processor(outbox_domain))

        assert len(_outbox_spans(span_exporter, "protean.outbox.publish")) == 2

    @pytest.mark.asyncio
    async def test_publish_span_attributes_and_parent(
        self, outbox_domain, span_exporter
    ):
        _persist_outbox_messages(outbox_domain, count=1)

        await _process_one_batch(await _new_processor(outbox_domain))

        (process_span,) = _outbox_spans(span_exporter, "protean.outbox.process")
        (publish_span,) = _outbox_spans(span_exporter, "protean.outbox.publish")
        assert publish_span.attributes["protean.outbox.message_id"] != ""
        assert "protean.outbox.stream_category" in publish_span.attributes
        assert publish_span.attributes["protean.outbox.message_type"] == "DummyEvent"
        assert publish_span.attributes["protean.outbox.is_external"] is False
        assert "protean.outbox.processor_id" in publish_span.attributes
        assert publish_span.parent is not None
        assert publish_span.parent.span_id == process_span.context.span_id

    @pytest.mark.asyncio
    async def test_publish_error_recorded_on_span(
        self, outbox_domain, span_exporter, monkeypatch
    ):
        _persist_outbox_messages(outbox_domain, count=1)
        processor = await _new_processor(outbox_domain)

        # Make broker publish fail
        monkeypatch.setattr(
            processor.broker,
            "publish",
            Mock(side_effect=RuntimeError("Broker down")),
        )

        await _process_one_batch(processor)

        (publish_span,) = _outbox_spans(span_exporter, "protean.outbox.publish")
        assert publish_span.status.status_code == StatusCode.ERROR
        assert "Broker down" in publish_span.status.description
        exception_events = [e for e in publish_span.events if e.name == "exception"]
        assert len(exception_events) == 1
        assert "Broker down" in exception_events[0].attributes["exception.message"]


@pytest.mark.database
class TestOutboxProcessorWithoutTelemetry:
    """OutboxProcessor works correctly when telemetry is not enabled."""

    @pytest.mark.asyncio
    async def test_process_batch_works_without_telemetry(self, outbox_domain):
        _persist_outbox_messages(outbox_domain, count=2)

        result = await _process_one_batch(await _new_processor(outbox_domain))

        assert result == 2
