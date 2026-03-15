"""Tests for OpenTelemetry span instrumentation on command processing,
handler dispatch, and query dispatch.

Verifies that:
- ``CommandProcessor.process()`` emits a ``protean.command.process`` span
  with the correct attributes (command type, id, stream, correlation_id).
- ``CommandProcessor.enrich()`` emits a child ``protean.command.enrich``
  span nested under the process span.
- ``HandlerMixin._handle()`` emits a ``protean.handler.execute`` span
  with handler name and type.
- ``QueryProcessor.dispatch()`` emits a ``protean.query.dispatch`` span.
- Errors in handlers record exceptions and set ERROR status on spans.
- Parent-child span relationships are correct.
"""

from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle, read


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class OpenAccount(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountCommandHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def open(self, command: OpenAccount):
        account = Account(account_id=command.account_id, name=command.name)
        current_domain.repository_for(Account).add(account)
        return {"opened": command.account_id}


class FailingCommand(BaseCommand):
    account_id = Identifier(identifier=True)


class FailingCommandHandler(BaseCommandHandler):
    @handle(FailingCommand)
    def fail(self, command: FailingCommand):
        raise RuntimeError("handler exploded")


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query: GetOrdersByCustomer):
        return [
            {"order_id": "order-1", "customer_id": query.customer_id, "status": "shipped"},
            {"order_id": "order-2", "customer_id": query.customer_id, "status": "pending"},
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing."""
    service_name = domain.normalized_name
    resource = Resource.create({"service.name": service_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.register(AccountCommandHandler, part_of=Account)
    test_domain.register(FailingCommand, part_of=Account)
    test_domain.register(FailingCommandHandler, part_of=Account)
    test_domain.register(OrderSummary)
    test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.init(traverse=False)


@pytest.fixture()
def span_exporter(test_domain):
    """Enable in-memory OTEL and return the span exporter."""
    return _init_telemetry_in_memory(test_domain)


# ---------------------------------------------------------------------------
# Tests: Command processing spans
# ---------------------------------------------------------------------------


class TestCommandProcessSpan:
    """CommandProcessor.process() emits ``protean.command.process``."""

    def test_process_emits_span_with_correct_name(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "protean.command.process" in span_names

    def test_process_span_has_command_type(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        assert process_span.attributes["protean.command.type"] == OpenAccount.__type__

    def test_process_span_has_command_id(self, test_domain, span_exporter):
        acct_id = str(uuid4())
        test_domain.process(
            OpenAccount(account_id=acct_id, name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        assert process_span.attributes["protean.command.id"] == acct_id

    def test_process_span_has_stream(self, test_domain, span_exporter):
        acct_id = str(uuid4())
        test_domain.process(
            OpenAccount(account_id=acct_id, name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        assert "protean.stream" in process_span.attributes
        assert process_span.attributes["protean.stream"] != ""

    def test_process_span_has_correlation_id(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        assert "protean.correlation_id" in process_span.attributes
        assert process_span.attributes["protean.correlation_id"] != ""


# ---------------------------------------------------------------------------
# Tests: Enrich child span
# ---------------------------------------------------------------------------


class TestCommandEnrichSpan:
    """CommandProcessor.enrich() emits a child ``protean.command.enrich``."""

    def test_enrich_span_emitted(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "protean.command.enrich" in span_names

    def test_enrich_is_child_of_process(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        enrich_span = next(s for s in spans if s.name == "protean.command.enrich")

        # The enrich span's parent should be the process span
        assert enrich_span.parent is not None
        assert enrich_span.parent.span_id == process_span.context.span_id

    def test_enrich_span_has_command_type(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        enrich_span = next(s for s in spans if s.name == "protean.command.enrich")
        assert enrich_span.attributes["protean.command.type"] == OpenAccount.__type__


# ---------------------------------------------------------------------------
# Tests: Handler execution span
# ---------------------------------------------------------------------------


class TestHandlerExecuteSpan:
    """HandlerMixin._handle() emits ``protean.handler.execute``."""

    def test_handler_span_emitted(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "protean.handler.execute" in span_names

    def test_handler_span_has_name_attribute(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")
        assert handler_span.attributes["protean.handler.name"] == "AccountCommandHandler"

    def test_handler_span_has_type_attribute(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")
        assert handler_span.attributes["protean.handler.type"] == "COMMAND_HANDLER"

    def test_handler_span_is_child_of_process(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        assert handler_span.parent is not None
        assert handler_span.parent.span_id == process_span.context.span_id


# ---------------------------------------------------------------------------
# Tests: Error spans
# ---------------------------------------------------------------------------


class TestErrorSpans:
    """Errors in handlers record exceptions and set ERROR status on spans."""

    def test_error_recorded_on_process_span(self, test_domain, span_exporter):
        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")

        assert process_span.status.status_code == StatusCode.ERROR
        assert "handler exploded" in process_span.status.description

    def test_exception_event_recorded_on_process_span(self, test_domain, span_exporter):
        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")

        # OTEL records exceptions as span events
        exception_events = [e for e in process_span.events if e.name == "exception"]
        assert len(exception_events) == 1
        assert "handler exploded" in exception_events[0].attributes["exception.message"]

    def test_error_recorded_on_handler_span(self, test_domain, span_exporter):
        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        assert handler_span.status.status_code == StatusCode.ERROR
        assert "handler exploded" in handler_span.status.description

    def test_exception_event_recorded_on_handler_span(self, test_domain, span_exporter):
        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        spans = span_exporter.get_finished_spans()
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        exception_events = [e for e in handler_span.events if e.name == "exception"]
        assert len(exception_events) == 1
        assert "handler exploded" in exception_events[0].attributes["exception.message"]


# ---------------------------------------------------------------------------
# Tests: Query dispatch spans
# ---------------------------------------------------------------------------


class TestQueryDispatchSpan:
    """QueryProcessor.dispatch() emits ``protean.query.dispatch``."""

    def test_query_dispatch_emits_span(self, test_domain, span_exporter):
        test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "protean.query.dispatch" in span_names

    def test_query_span_has_query_type(self, test_domain, span_exporter):
        test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        spans = span_exporter.get_finished_spans()
        query_span = next(s for s in spans if s.name == "protean.query.dispatch")
        assert query_span.attributes["protean.query.type"] == GetOrdersByCustomer.__type__

    def test_query_span_has_handler_name(self, test_domain, span_exporter):
        test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        spans = span_exporter.get_finished_spans()
        query_span = next(s for s in spans if s.name == "protean.query.dispatch")
        assert query_span.attributes["protean.handler.name"] == "OrderSummaryQueryHandler"

    def test_handler_execute_span_inside_query_dispatch(self, test_domain, span_exporter):
        test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        spans = span_exporter.get_finished_spans()
        query_span = next(s for s in spans if s.name == "protean.query.dispatch")
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        # Handler span should be a child of query dispatch span
        assert handler_span.parent is not None
        assert handler_span.parent.span_id == query_span.context.span_id

    def test_query_handler_type_attribute(self, test_domain, span_exporter):
        test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        spans = span_exporter.get_finished_spans()
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")
        assert handler_span.attributes["protean.handler.type"] == "QUERY_HANDLER"


# ---------------------------------------------------------------------------
# Tests: Parent-child span relationships
# ---------------------------------------------------------------------------


class TestSpanRelationships:
    """Verify the full parent-child span tree during command processing."""

    def test_full_span_tree(self, test_domain, span_exporter):
        """process → enrich (child) + handler.execute (child)."""
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        process_span = next(s for s in spans if s.name == "protean.command.process")
        enrich_span = next(s for s in spans if s.name == "protean.command.enrich")
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")

        # All spans share the same trace ID
        assert enrich_span.context.trace_id == process_span.context.trace_id
        assert handler_span.context.trace_id == process_span.context.trace_id

        # Process is the root (no parent or parent from external context)
        # Enrich and handler are children of process
        assert enrich_span.parent.span_id == process_span.context.span_id
        assert handler_span.parent.span_id == process_span.context.span_id

    def test_all_spans_share_trace_id(self, test_domain, span_exporter):
        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        spans = span_exporter.get_finished_spans()
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1


# ---------------------------------------------------------------------------
# Tests: No-op when telemetry not enabled
# ---------------------------------------------------------------------------


class TestNoOpWhenDisabled:
    """When telemetry is not enabled, processing should work without spans."""

    def test_command_processing_works_without_telemetry(self, test_domain):
        acct_id = str(uuid4())
        result = test_domain.process(
            OpenAccount(account_id=acct_id, name="Acme"),
            asynchronous=False,
        )
        assert result == {"opened": acct_id}

    def test_query_dispatch_works_without_telemetry(self, test_domain):
        result = test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))
        assert isinstance(result, list)
        assert len(result) == 2

    def test_failing_handler_propagates_without_telemetry(self, test_domain):
        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )
