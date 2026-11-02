"""End-to-end integration tests for the unified OTel span hierarchy and
Observatory trace emission.

Validates:
- Full span tree from command → handler → UoW → repository → event store,
  and from engine.handle_message → handler → UoW.
- Parent-child relationships are correct at every level (no orphaned spans,
  no duplicate parent relationships).
- Attributes at each span level are complementary (engine spans carry routing
  context; handler spans carry type detail; UoW spans carry commit metrics).
- Observatory traces (via TraceEmitter) are emitted alongside OTel spans
  and tell a consistent story for the same message lifecycle.
- Everything works correctly both with OTel enabled and disabled.
"""

import json
from uuid import uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.tracing import TRACE_STREAM, TraceEmitter
from protean.utils.eventing import Message
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


class Customer(BaseAggregate):
    customer_id = Identifier(identifier=True)
    name = String(required=True)
    email = String(required=True)


class CustomerRegistered(BaseEvent):
    customer_id = Identifier(identifier=True)
    name = String(required=True)
    email = String(required=True)


class RegisterCustomer(BaseCommand):
    customer_id = Identifier(identifier=True)
    name = String(required=True)
    email = String(required=True)


class CustomerCommandHandler(BaseCommandHandler):
    @handle(RegisterCustomer)
    def register(self, command: RegisterCustomer):
        customer = Customer(
            customer_id=command.customer_id,
            name=command.name,
            email=command.email,
        )
        customer.raise_(
            CustomerRegistered(
                customer_id=command.customer_id,
                name=command.name,
                email=command.email,
            )
        )
        current_domain.repository_for(Customer).add(customer)
        return {"registered": command.customer_id}


class FailingRegisterCustomer(BaseCommand):
    customer_id = Identifier(identifier=True)


class FailingCustomerHandler(BaseCommandHandler):
    @handle(FailingRegisterCustomer)
    def register(self, command: FailingRegisterCustomer):
        raise RuntimeError("registration failed")


class CustomerEventHandler(BaseEventHandler):
    @handle(CustomerRegistered)
    def on_registered(self, event: CustomerRegistered):
        pass  # Just consume the event


# Event-sourced variant for testing event store spans
class WalletCreated(BaseEvent):
    wallet_id = Identifier(identifier=True)
    owner = String(required=True)


class Wallet(BaseAggregate):
    wallet_id = Identifier(identifier=True)
    owner = String(required=True)

    @classmethod
    def create(cls, wallet_id: str, owner: str) -> "Wallet":
        wallet = cls(wallet_id=wallet_id, owner=owner)
        wallet.raise_(WalletCreated(wallet_id=wallet_id, owner=owner))
        return wallet

    @apply
    def on_wallet_created(self, event: WalletCreated) -> None:
        self.owner = event.owner


class CreateWallet(BaseCommand):
    wallet_id = Identifier(identifier=True)
    owner = String(required=True)


class WalletCommandHandler(BaseCommandHandler):
    @handle(CreateWallet)
    def create(self, command: CreateWallet):
        wallet = Wallet.create(wallet_id=command.wallet_id, owner=command.owner)
        current_domain.repository_for(Wallet).add(wallet)
        return {"created": command.wallet_id}


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


def _make_event_message(domain) -> Message:
    """Helper to create a valid event Message for engine tests."""
    uid = str(uuid4())
    customer = Customer(
        customer_id=uid,
        name="Test",
        email="test@example.com",
    )
    customer.raise_(
        CustomerRegistered(
            customer_id=uid,
            name="Test",
            email="test@example.com",
        )
    )
    return Message.from_domain_object(customer._events[-1])


def _span_by_name(spans, name):
    """Find a span by name from a list of finished spans."""
    return next((s for s in spans if s.name == name), None)


def _spans_by_name(spans, name):
    """Find all spans matching a name."""
    return [s for s in spans if s.name == name]


class RecordingRedis:
    """Stands in for the Redis server that TraceEmitter writes traces to."""

    def __init__(self):
        self.stream_entries = []

    def xadd(self, name, fields, **kwargs):
        self.stream_entries.append((name, fields))

    def publish(self, channel, message):
        pass

    def pubsub_numsub(self, channel):
        return []

    def traces(self):
        return [
            json.loads(fields["data"])
            for name, fields in self.stream_entries
            if name == TRACE_STREAM
        ]


def _record_traces(emitter: TraceEmitter) -> RecordingRedis:
    """Point the emitter at a recording Redis stand-in with persistence on."""
    redis = RecordingRedis()
    emitter._redis = redis
    emitter._persist = True
    emitter._initialized = True
    return redis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(CustomerRegistered, part_of=Customer)
    test_domain.register(RegisterCustomer, part_of=Customer)
    test_domain.register(CustomerCommandHandler, part_of=Customer)
    test_domain.register(FailingRegisterCustomer, part_of=Customer)
    test_domain.register(FailingCustomerHandler, part_of=Customer)
    test_domain.register(CustomerEventHandler, part_of=Customer)
    test_domain.register(Wallet, event_sourced=True)
    test_domain.register(WalletCreated, part_of=Wallet)
    test_domain.register(CreateWallet, part_of=Wallet)
    test_domain.register(WalletCommandHandler, part_of=Wallet)
    test_domain.init(traverse=False)


@pytest.fixture()
def span_exporter(test_domain):
    """Enable in-memory OTEL and return the span exporter."""
    return _init_telemetry_in_memory(test_domain)


# ---------------------------------------------------------------------------
# Tests: Full command processing span tree
# ---------------------------------------------------------------------------


class TestCommandProcessingSpanTree:
    """Validate the complete span tree for synchronous command processing.

    Expected hierarchy:
        protean.command.process (root)
        ├── protean.command.enrich
        ├── protean.event_store.append (command persist)
        └── protean.handler.execute
            └── protean.repository.add
                └── protean.uow.commit
                    └── protean.event_store.append (event persist)
    """

    def test_no_orphaned_spans(self, test_domain, span_exporter):
        """Every span except the root has a parent within the same trace."""
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Grace", email="g@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_ids = {s.context.span_id for s in spans}
        trace_id = spans[0].context.trace_id

        for span in spans:
            assert span.context.trace_id == trace_id, (
                f"Span '{span.name}' has wrong trace_id"
            )
            if span.parent is not None:
                # Every non-root span's parent must exist within this trace
                assert span.parent.span_id in span_ids, (
                    f"Span '{span.name}' has parent span_id not in the span tree"
                )
                assert span.parent.trace_id == trace_id, (
                    f"Span '{span.name}' parent has different trace_id"
                )


# ---------------------------------------------------------------------------
# Tests: Complementary attributes (no redundancy)
# ---------------------------------------------------------------------------


class TestComplementaryAttributes:
    """Verify that each span layer adds complementary, not redundant, attributes.

    Design principle:
    - Engine span: routing context (message ID, type, stream, subscription type)
    - Handler span: handler identity (name, type)
    - UoW span: commit metrics (event count, session count)
    - Repository span: persistence target (aggregate type, provider)
    - Event store span: storage detail (stream, message type, position)
    """

    def test_event_store_span_attributes(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(customer_id=str(uuid4()), name="ES", email="e@test.com"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        append_spans = _spans_by_name(spans, "protean.event_store.append")
        assert len(append_spans) >= 1

        # Event store span provides storage detail
        for append_span in append_spans:
            assert "protean.event_store.stream" in append_span.attributes
            assert "protean.event_store.message_type" in append_span.attributes
            assert "protean.event_store.position" in append_span.attributes


# ---------------------------------------------------------------------------
# Tests: Engine-level span hierarchy
# ---------------------------------------------------------------------------


class TestEngineSpanHierarchy:
    """Validate span hierarchy when Engine.handle_message() processes events.

    Expected hierarchy:
        protean.engine.handle_message (root)
        └── protean.handler.execute
    """

    @pytest.fixture()
    def engine(self, test_domain):
        return Engine(domain=test_domain, test_mode=True)

    @pytest.mark.asyncio
    async def test_engine_handler_span_has_complementary_type(
        self, test_domain, span_exporter, engine
    ):
        """Handler span adds handler.type which engine span does not have."""
        message = _make_event_message(test_domain)
        await engine.handle_message(CustomerEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")
        handler_span = _span_by_name(spans, "protean.handler.execute")

        # Engine span has subscription_type (routing); handler span has handler.type (identity)
        assert "protean.subscription_type" in engine_span.attributes
        assert "protean.handler.type" in handler_span.attributes
        assert handler_span.attributes["protean.handler.type"] == "EVENT_HANDLER"


# ---------------------------------------------------------------------------
# Tests: Error propagation through span tree
# ---------------------------------------------------------------------------


class TestErrorSpanPropagation:
    """Verify errors are recorded on the correct spans through the hierarchy."""

    def test_error_spans_share_trace_id(self, test_domain, span_exporter):
        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingRegisterCustomer(customer_id=str(uuid4())),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1


# ---------------------------------------------------------------------------
# Tests: Observatory trace emission alongside OTel spans
# ---------------------------------------------------------------------------


class TestObservatoryTraceAlignment:
    """Verify that Observatory traces (TraceEmitter) are emitted alongside OTel spans.

    When command processing happens synchronously via domain.process(), the
    CommandProcessor emits handler.started/completed/failed traces. These must
    align with the OTel span boundaries.
    """

    def test_observatory_traces_emitted_during_sync_processing(
        self, test_domain, span_exporter
    ):
        """Both OTel spans and Observatory traces should fire for sync commands."""
        redis = _record_traces(test_domain.trace_emitter)

        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Obs", email="obs@test.com"
            ),
            asynchronous=False,
        )

        # OTel spans should be present
        span_names = {s.name for s in span_exporter.get_finished_spans()}
        assert "protean.command.process" in span_names
        assert "protean.handler.execute" in span_names

        # Observatory traces should also be emitted
        traces = redis.traces()
        trace_events = [t["event"] for t in traces]
        assert "handler.started" in trace_events
        assert "handler.completed" in trace_events

        completed = next(
            t
            for t in traces
            if t["event"] == "handler.completed"
            and t["handler"] == "CustomerCommandHandler"
        )
        assert completed["duration_ms"] >= 0

    def test_observatory_error_traces_on_failure(self, test_domain, span_exporter):
        redis = _record_traces(test_domain.trace_emitter)

        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingRegisterCustomer(customer_id=str(uuid4())),
                asynchronous=False,
            )

        # Should have handler.started and handler.failed
        traces = redis.traces()
        trace_events = [t["event"] for t in traces]
        assert "handler.started" in trace_events
        assert "handler.failed" in trace_events

        failed = next(t for t in traces if t["event"] == "handler.failed")
        assert failed["status"] == "error"
        assert "registration failed" in failed["error"]


class TestEngineObservatoryTraceAlignment:
    """Verify Observatory traces from Engine.handle_message()."""

    @pytest.fixture()
    def engine(self, test_domain):
        return Engine(domain=test_domain, test_mode=True)

    @pytest.mark.asyncio
    async def test_engine_observatory_traces_match_otel_span(
        self, test_domain, span_exporter, engine
    ):
        """Engine.handle_message() emits both OTel spans and Observatory traces,
        and both report the same handler name and message ID."""
        message = _make_event_message(test_domain)
        redis = _record_traces(engine.emitter)

        await engine.handle_message(CustomerEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")
        assert engine_span is not None

        traces = redis.traces()
        trace_events = [t["event"] for t in traces]
        assert "handler.started" in trace_events
        assert "handler.completed" in trace_events

        started = next(t for t in traces if t["event"] == "handler.started")
        completed = next(t for t in traces if t["event"] == "handler.completed")
        assert engine_span.attributes["protean.handler.name"] == completed["handler"]
        assert engine_span.attributes["protean.message.id"] == started["message_id"]


# ---------------------------------------------------------------------------
# Tests: OTel disabled - everything still works
# ---------------------------------------------------------------------------


class TestOTelDisabled:
    """Verify that all processing works correctly when OTel is not enabled."""

    def test_event_sourced_works(self, test_domain):
        wid = str(uuid4())
        result = test_domain.process(
            CreateWallet(wallet_id=wid, owner="NoOTel"),
            asynchronous=False,
        )
        assert result == {"created": wid}

    def test_observatory_traces_still_emit_without_otel(self, test_domain):
        """Observatory traces should fire regardless of OTel state."""
        redis = _record_traces(test_domain.trace_emitter)

        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Trace", email="t@test.com"
            ),
            asynchronous=False,
        )

        trace_events = [t["event"] for t in redis.traces()]
        assert "handler.started" in trace_events
        assert "handler.completed" in trace_events
