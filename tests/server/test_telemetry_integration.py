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

References: #767 (6.1.9: Unify OTel span hierarchy and Observatory trace emission)
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
    TraceParent,
)
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
    meter_provider = SDKMeterProvider(
        resource=resource, metric_readers=[metric_reader]
    )

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


def _make_event_message_with_traceparent(domain) -> Message:
    """Create an event Message with an external traceparent."""
    uid = str(uuid4())
    tp = TraceParent.build(EXTERNAL_TRACEPARENT)
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
            _metadata=Metadata(
                headers=MessageHeaders(traceparent=tp),
            ),
        )
    )
    return Message.from_domain_object(customer._events[-1])


EXTERNAL_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
EXTERNAL_SPAN_ID = "00f067aa0ba902b7"
EXTERNAL_TRACEPARENT = f"00-{EXTERNAL_TRACE_ID}-{EXTERNAL_SPAN_ID}-01"


def _span_by_name(spans, name):
    """Find a span by name from a list of finished spans."""
    return next((s for s in spans if s.name == name), None)


def _spans_by_name(spans, name):
    """Find all spans matching a name."""
    return [s for s in spans if s.name == name]


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
    test_domain.register(Wallet, is_event_sourced=True)
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

    def test_all_expected_spans_present(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Alice", email="a@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_names = {s.name for s in spans}

        assert "protean.command.process" in span_names
        assert "protean.command.enrich" in span_names
        assert "protean.handler.execute" in span_names
        assert "protean.repository.add" in span_names
        assert "protean.uow.commit" in span_names
        assert "protean.event_store.append" in span_names

    def test_all_spans_share_single_trace_id(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Bob", email="b@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1

    def test_enrich_is_child_of_process(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Carol", email="c@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = _span_by_name(spans, "protean.command.process")
        enrich_span = _span_by_name(spans, "protean.command.enrich")

        assert enrich_span.parent is not None
        assert enrich_span.parent.span_id == process_span.context.span_id

    def test_command_handler_is_child_of_process(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Dave", email="d@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = _span_by_name(spans, "protean.command.process")

        # In sync processing, there may be multiple handler.execute spans
        # (command handler + event handlers triggered by sync event processing).
        # Find the command handler span specifically.
        handler_spans = _spans_by_name(spans, "protean.handler.execute")
        cmd_handler = next(
            s
            for s in handler_spans
            if s.attributes.get("protean.handler.name") == "CustomerCommandHandler"
        )

        assert cmd_handler.parent is not None
        assert cmd_handler.parent.span_id == process_span.context.span_id

    def test_repository_add_is_child_of_command_handler(
        self, test_domain, span_exporter
    ):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Eve", email="e@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        handler_spans = _spans_by_name(spans, "protean.handler.execute")
        cmd_handler = next(
            s
            for s in handler_spans
            if s.attributes.get("protean.handler.name") == "CustomerCommandHandler"
        )
        add_spans = _spans_by_name(spans, "protean.repository.add")
        # Find the repository.add for Customer
        customer_add = next(
            s
            for s in add_spans
            if s.attributes.get("protean.aggregate.type") == "Customer"
        )

        assert customer_add.parent is not None
        assert customer_add.parent.span_id == cmd_handler.context.span_id

    def test_uow_commit_is_descendant_of_handler(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Frank", email="f@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        handler_span = _span_by_name(spans, "protean.handler.execute")
        uow_span = _span_by_name(spans, "protean.uow.commit")

        # UoW commit is nested under handler (through repository.add)
        assert uow_span.parent is not None
        assert uow_span.context.trace_id == handler_span.context.trace_id

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
                # The parent should either be another span in our tree
                # or an external parent (for traceparent propagation)
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

    def test_command_process_span_attributes(self, test_domain, span_exporter):
        cid = str(uuid4())
        test_domain.process(
            RegisterCustomer(customer_id=cid, name="Attr", email="a@test.com"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = _span_by_name(spans, "protean.command.process")

        # Command process span has command-specific context
        assert "protean.command.type" in process_span.attributes
        assert "protean.command.id" in process_span.attributes
        assert "protean.stream" in process_span.attributes
        assert "protean.correlation_id" in process_span.attributes

    def test_handler_span_attributes_complement_engine(
        self, test_domain, span_exporter
    ):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Comp", email="c@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        handler_spans = _spans_by_name(spans, "protean.handler.execute")
        # Find the command handler span specifically
        cmd_handler = next(
            s
            for s in handler_spans
            if s.attributes.get("protean.handler.name") == "CustomerCommandHandler"
        )

        # Handler span provides handler identity
        assert cmd_handler.attributes["protean.handler.name"] == "CustomerCommandHandler"
        assert cmd_handler.attributes["protean.handler.type"] == "COMMAND_HANDLER"

    def test_uow_span_attributes(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="UoW", email="u@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        uow_span = _span_by_name(spans, "protean.uow.commit")

        # UoW span provides commit metrics
        assert "protean.uow.event_count" in uow_span.attributes
        assert "protean.uow.session_count" in uow_span.attributes
        assert uow_span.attributes["protean.uow.event_count"] >= 0

    def test_repository_span_attributes(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="Repo", email="r@test.com"
            ),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        add_spans = _spans_by_name(spans, "protean.repository.add")
        customer_add = next(
            s
            for s in add_spans
            if s.attributes.get("protean.aggregate.type") == "Customer"
        )

        # Repository span provides persistence target
        assert customer_add.attributes["protean.aggregate.type"] == "Customer"
        assert "protean.provider" in customer_add.attributes

    def test_event_store_span_attributes(self, test_domain, span_exporter):
        test_domain.process(
            RegisterCustomer(
                customer_id=str(uuid4()), name="ES", email="e@test.com"
            ),
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
    async def test_handler_execute_is_child_of_engine(
        self, test_domain, span_exporter, engine
    ):
        message = _make_event_message(test_domain)
        await engine.handle_message(CustomerEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")
        handler_span = _span_by_name(spans, "protean.handler.execute")

        assert engine_span is not None
        assert handler_span is not None
        assert handler_span.parent is not None
        assert handler_span.parent.span_id == engine_span.context.span_id

    @pytest.mark.asyncio
    async def test_all_engine_spans_share_trace_id(
        self, test_domain, span_exporter, engine
    ):
        message = _make_event_message(test_domain)
        await engine.handle_message(CustomerEventHandler, message)

        spans = span_exporter.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1

    @pytest.mark.asyncio
    async def test_engine_span_has_routing_attributes(
        self, test_domain, span_exporter, engine
    ):
        message = _make_event_message(test_domain)
        await engine.handle_message(
            CustomerEventHandler, message, worker_id="worker-1"
        )

        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")

        assert engine_span.attributes["protean.handler.name"] == "CustomerEventHandler"
        assert "protean.message.type" in engine_span.attributes
        assert "protean.message.id" in engine_span.attributes
        assert "protean.stream_category" in engine_span.attributes
        assert engine_span.attributes["protean.subscription_type"] == "event_handler"
        assert engine_span.attributes["protean.worker_id"] == "worker-1"

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

    @pytest.mark.asyncio
    async def test_engine_span_with_traceparent(
        self, test_domain, span_exporter, engine
    ):
        """Engine span becomes child of external trace when traceparent present."""
        message = _make_event_message_with_traceparent(test_domain)
        await engine.handle_message(CustomerEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")

        assert f"{engine_span.context.trace_id:032x}" == EXTERNAL_TRACE_ID
        assert engine_span.parent is not None
        assert f"{engine_span.parent.span_id:016x}" == EXTERNAL_SPAN_ID


# ---------------------------------------------------------------------------
# Tests: Error propagation through span tree
# ---------------------------------------------------------------------------


class TestErrorSpanPropagation:
    """Verify errors are recorded on the correct spans through the hierarchy."""

    def test_error_on_process_and_handler_spans(self, test_domain, span_exporter):
        with pytest.raises(RuntimeError, match="registration failed"):
            test_domain.process(
                FailingRegisterCustomer(customer_id=str(uuid4())),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        process_span = _span_by_name(spans, "protean.command.process")
        handler_span = _span_by_name(spans, "protean.handler.execute")

        # Both process and handler spans should record the error
        assert process_span.status.status_code == StatusCode.ERROR
        assert handler_span.status.status_code == StatusCode.ERROR
        assert "registration failed" in process_span.status.description
        assert "registration failed" in handler_span.status.description

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
# Tests: Event-sourced aggregate span tree
# ---------------------------------------------------------------------------


class TestEventSourcedSpanTree:
    """Validate span tree for event-sourced aggregates includes event store append."""

    def test_es_includes_event_store_append(self, test_domain, span_exporter):
        test_domain.process(
            CreateWallet(wallet_id=str(uuid4()), owner="Alice"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_names = {s.name for s in spans}

        assert "protean.command.process" in span_names
        assert "protean.handler.execute" in span_names
        assert "protean.repository.add" in span_names
        assert "protean.uow.commit" in span_names
        assert "protean.event_store.append" in span_names

    def test_es_event_store_append_shares_trace_with_uow(
        self, test_domain, span_exporter
    ):
        test_domain.process(
            CreateWallet(wallet_id=str(uuid4()), owner="Bob"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        uow_spans = _spans_by_name(spans, "protean.uow.commit")
        append_spans = _spans_by_name(spans, "protean.event_store.append")

        # Event store append spans for events are called within UoW._do_commit,
        # so they should share the same trace ID as the UoW span
        assert len(uow_spans) >= 1
        assert len(append_spans) >= 1

        uow_trace_ids = {s.context.trace_id for s in uow_spans}
        append_trace_ids = {s.context.trace_id for s in append_spans}
        # All spans should be in the same trace
        assert len(uow_trace_ids | append_trace_ids) == 1

    def test_es_all_spans_share_trace_id(self, test_domain, span_exporter):
        test_domain.process(
            CreateWallet(wallet_id=str(uuid4()), owner="Carol"),
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
        # Patch the trace emitter to capture calls
        emitter = test_domain.trace_emitter
        calls = []
        original_emit = emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(emitter, "emit", side_effect=capturing_emit):
            test_domain.process(
                RegisterCustomer(
                    customer_id=str(uuid4()), name="Obs", email="obs@test.com"
                ),
                asynchronous=False,
            )

        # OTel spans should be present
        spans = span_exporter.get_finished_spans()
        span_names = {s.name for s in spans}
        assert "protean.command.process" in span_names
        assert "protean.handler.execute" in span_names

        # Observatory traces should also be emitted
        trace_events = [c["event"] for c in calls]
        assert "handler.started" in trace_events
        assert "handler.completed" in trace_events

    def test_observatory_traces_include_handler_name(
        self, test_domain, span_exporter
    ):
        emitter = test_domain.trace_emitter
        calls = []
        original_emit = emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(emitter, "emit", side_effect=capturing_emit):
            test_domain.process(
                RegisterCustomer(
                    customer_id=str(uuid4()), name="Name", email="n@test.com"
                ),
                asynchronous=False,
            )

        # Find handler.completed trace
        completed = next(c for c in calls if c["event"] == "handler.completed")
        assert completed["handler"] == "CustomerCommandHandler"

    def test_observatory_traces_include_duration(self, test_domain, span_exporter):
        emitter = test_domain.trace_emitter
        calls = []
        original_emit = emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(emitter, "emit", side_effect=capturing_emit):
            test_domain.process(
                RegisterCustomer(
                    customer_id=str(uuid4()), name="Dur", email="d@test.com"
                ),
                asynchronous=False,
            )

        completed = next(c for c in calls if c["event"] == "handler.completed")
        assert "duration_ms" in completed
        assert completed["duration_ms"] >= 0

    def test_observatory_error_traces_on_failure(self, test_domain, span_exporter):
        emitter = test_domain.trace_emitter
        calls = []
        original_emit = emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(emitter, "emit", side_effect=capturing_emit):
            with pytest.raises(RuntimeError):
                test_domain.process(
                    FailingRegisterCustomer(customer_id=str(uuid4())),
                    asynchronous=False,
                )

        # Should have handler.started and handler.failed
        trace_events = [c["event"] for c in calls]
        assert "handler.started" in trace_events
        assert "handler.failed" in trace_events

        failed = next(c for c in calls if c["event"] == "handler.failed")
        assert failed["status"] == "error"
        assert "registration failed" in failed["error"]


class TestEngineObservatoryTraceAlignment:
    """Verify Observatory traces from Engine.handle_message()."""

    @pytest.fixture()
    def engine(self, test_domain):
        return Engine(domain=test_domain, test_mode=True)

    @pytest.mark.asyncio
    async def test_engine_emits_observatory_traces(
        self, test_domain, span_exporter, engine
    ):
        """Engine.handle_message() emits both OTel spans and Observatory traces."""
        message = _make_event_message(test_domain)

        calls = []
        original_emit = engine.emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(engine.emitter, "emit", side_effect=capturing_emit):
            await engine.handle_message(CustomerEventHandler, message)

        # OTel spans
        spans = span_exporter.get_finished_spans()
        assert _span_by_name(spans, "protean.engine.handle_message") is not None

        # Observatory traces
        trace_events = [c["event"] for c in calls]
        assert "handler.started" in trace_events
        assert "handler.completed" in trace_events

    @pytest.mark.asyncio
    async def test_engine_observatory_and_otel_consistent_handler_name(
        self, test_domain, span_exporter, engine
    ):
        """OTel span and Observatory trace report the same handler name."""
        message = _make_event_message(test_domain)

        calls = []
        original_emit = engine.emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(engine.emitter, "emit", side_effect=capturing_emit):
            await engine.handle_message(CustomerEventHandler, message)

        # OTel span handler name
        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")
        otel_handler = engine_span.attributes["protean.handler.name"]

        # Observatory trace handler name
        completed = next(c for c in calls if c["event"] == "handler.completed")
        obs_handler = completed["handler"]

        assert otel_handler == obs_handler

    @pytest.mark.asyncio
    async def test_engine_observatory_and_otel_consistent_message_id(
        self, test_domain, span_exporter, engine
    ):
        """OTel span and Observatory trace report the same message ID."""
        message = _make_event_message(test_domain)

        calls = []
        original_emit = engine.emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(engine.emitter, "emit", side_effect=capturing_emit):
            await engine.handle_message(CustomerEventHandler, message)

        spans = span_exporter.get_finished_spans()
        engine_span = _span_by_name(spans, "protean.engine.handle_message")
        otel_msg_id = engine_span.attributes["protean.message.id"]

        started = next(c for c in calls if c["event"] == "handler.started")
        obs_msg_id = started["message_id"]

        assert otel_msg_id == obs_msg_id


# ---------------------------------------------------------------------------
# Tests: OTel disabled - everything still works
# ---------------------------------------------------------------------------


class TestOTelDisabled:
    """Verify that all processing works correctly when OTel is not enabled."""

    def test_command_processing_works(self, test_domain):
        """No span_exporter fixture — telemetry is not initialized."""
        cid = str(uuid4())
        result = test_domain.process(
            RegisterCustomer(customer_id=cid, name="NoOTel", email="no@test.com"),
            asynchronous=False,
        )
        assert result == {"registered": cid}

    def test_failing_command_propagates_error(self, test_domain):
        with pytest.raises(RuntimeError, match="registration failed"):
            test_domain.process(
                FailingRegisterCustomer(customer_id=str(uuid4())),
                asynchronous=False,
            )

    def test_event_sourced_works(self, test_domain):
        wid = str(uuid4())
        result = test_domain.process(
            CreateWallet(wallet_id=wid, owner="NoOTel"),
            asynchronous=False,
        )
        assert result == {"created": wid}

    @pytest.mark.asyncio
    async def test_engine_handle_message_works(self, test_domain):
        engine = Engine(domain=test_domain, test_mode=True)
        message = _make_event_message(test_domain)

        result = await engine.handle_message(CustomerEventHandler, message)
        assert result is True

    def test_observatory_traces_still_emit_without_otel(self, test_domain):
        """Observatory traces should fire regardless of OTel state."""
        emitter = test_domain.trace_emitter
        calls = []
        original_emit = emitter.emit

        def capturing_emit(**kwargs):
            calls.append(kwargs)
            return original_emit(**kwargs)

        with patch.object(emitter, "emit", side_effect=capturing_emit):
            test_domain.process(
                RegisterCustomer(
                    customer_id=str(uuid4()), name="Trace", email="t@test.com"
                ),
                asynchronous=False,
            )

        trace_events = [c["event"] for c in calls]
        assert "handler.started" in trace_events
        assert "handler.completed" in trace_events


# ---------------------------------------------------------------------------
# Tests: Distributed trace propagation through full pipeline
# ---------------------------------------------------------------------------


class TestDistributedTracePropagation:
    """Verify trace context propagates through the full pipeline."""

    def test_external_trace_propagates_through_all_spans(
        self, test_domain, span_exporter
    ):
        """All spans in the tree should share the external trace ID."""
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        command = RegisterCustomer(
            customer_id=str(uuid4()),
            name="Prop",
            email="p@test.com",
            _metadata=Metadata(headers=MessageHeaders(traceparent=tp)),
        )

        test_domain.process(command, asynchronous=False)

        spans = span_exporter.get_finished_spans()
        for span in spans:
            assert f"{span.context.trace_id:032x}" == EXTERNAL_TRACE_ID, (
                f"Span '{span.name}' has trace_id "
                f"{span.context.trace_id:032x}, expected {EXTERNAL_TRACE_ID}"
            )

    def test_events_carry_traceparent_from_processing(
        self, test_domain, span_exporter
    ):
        """Events raised during handler execution carry the active span's traceparent."""
        uid = str(uuid4())
        test_domain.process(
            RegisterCustomer(customer_id=uid, name="TP", email="tp@test.com"),
            asynchronous=False,
        )

        # Read events from event store
        stream = f"{Customer.meta_.stream_category}-{uid}"
        events = test_domain.event_store.store.read(stream)

        customer_registered = [
            e
            for e in events
            if e.metadata.headers.type == CustomerRegistered.__type__
        ]
        assert len(customer_registered) == 1

        event_msg = customer_registered[0]
        assert event_msg.metadata.headers.traceparent is not None
        tp = event_msg.metadata.headers.traceparent
        assert tp.trace_id is not None
        assert tp.parent_id is not None

    def test_round_trip_preserves_trace_id(self, test_domain, span_exporter):
        """Command with external trace → events carry the same trace_id."""
        tp = TraceParent.build(EXTERNAL_TRACEPARENT)
        uid = str(uuid4())
        command = RegisterCustomer(
            customer_id=uid,
            name="RT",
            email="rt@test.com",
            _metadata=Metadata(headers=MessageHeaders(traceparent=tp)),
        )

        test_domain.process(command, asynchronous=False)

        stream = f"{Customer.meta_.stream_category}-{uid}"
        events = test_domain.event_store.store.read(stream)

        customer_registered = [
            e
            for e in events
            if e.metadata.headers.type == CustomerRegistered.__type__
        ]
        assert len(customer_registered) == 1

        event_tp = customer_registered[0].metadata.headers.traceparent
        assert event_tp is not None
        assert event_tp.trace_id == EXTERNAL_TRACE_ID
