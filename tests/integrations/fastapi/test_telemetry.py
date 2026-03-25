"""Tests for FastAPI OpenTelemetry auto-instrumentation.

Verifies that:
- ``instrument_app()`` applies OTEL instrumentation to a FastAPI app.
- HTTP request spans use the domain-scoped tracer provider.
- HTTP spans automatically parent command processing spans via context
  propagation.
- Instrumentation is a no-op when telemetry is disabled.
- Instrumentation is a no-op when OTEL packages are not installed.
- Double-instrumentation is prevented.
- ``excluded_urls`` parameter suppresses tracing for matched routes.
"""

from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.integrations.fastapi import DomainContextMiddleware, instrument_app
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer_name = String(required=True)


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer_name = String(required=True)


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder):
        order = Order(order_id=command.order_id, customer_name=command.customer_name)
        current_domain.repository_for(Order).add(order)
        return {"placed": command.order_id}


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


def _find_root_http_span(spans):
    """Find the root HTTP span (not a child send/receive span)."""
    _http_methods = ("GET", "POST", "PUT", "PATCH", "DELETE")
    span = next(
        (s for s in spans if s.parent is None and s.name.startswith(_http_methods)),
        None,
    )
    assert span is not None, f"No root HTTP span found among: {[s.name for s in spans]}"
    return span


def _make_app(domain, *, excluded_urls=None):
    """Create a FastAPI app with DomainContextMiddleware and telemetry."""
    app = FastAPI()

    app.add_middleware(
        DomainContextMiddleware,
        route_domain_map={"/orders": domain},
    )

    instrument_app(app, domain, excluded_urls=excluded_urls)

    @app.post("/orders")
    def create_order():
        order_id = str(uuid4())
        current_domain.process(
            PlaceOrder(order_id=order_id, customer_name="Alice"),
            asynchronous=False,
        )
        return {"order_id": order_id}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.init(traverse=False)


@pytest.fixture()
def span_exporter(test_domain):
    """Enable in-memory OTEL and return the span exporter."""
    return _init_telemetry_in_memory(test_domain)


# ---------------------------------------------------------------------------
# Tests: instrument_app applies instrumentation
# ---------------------------------------------------------------------------


class TestInstrumentApp:
    """instrument_app() applies OTEL instrumentation to a FastAPI app."""

    def test_returns_true_when_telemetry_enabled(self, test_domain, span_exporter):
        """instrument_app returns True when instrumentation is applied."""
        test_domain.config["telemetry"]["enabled"] = True
        app = FastAPI()
        result = instrument_app(app, test_domain)
        assert result is True

    def test_returns_false_when_telemetry_disabled(self, test_domain):
        """instrument_app returns False when telemetry is disabled."""
        test_domain.config["telemetry"]["enabled"] = False
        app = FastAPI()
        result = instrument_app(app, test_domain)
        assert result is False

    def test_prevents_double_instrumentation(self, test_domain, span_exporter):
        """Second call to instrument_app on same app returns False."""
        test_domain.config["telemetry"]["enabled"] = True
        app = FastAPI()
        assert instrument_app(app, test_domain) is True
        assert instrument_app(app, test_domain) is False

    def test_passes_excluded_urls(self, test_domain, span_exporter):
        """excluded_urls parameter is forwarded to the instrumentor."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain, excluded_urls="health")
        client = TestClient(app)

        # Request to excluded URL should not produce HTTP spans
        client.get("/health")

        spans = span_exporter.get_finished_spans()
        http_spans = [s for s in spans if s.name.startswith("GET")]
        assert len(http_spans) == 0


# ---------------------------------------------------------------------------
# Tests: HTTP spans created with domain-scoped provider
# ---------------------------------------------------------------------------


class TestHttpSpans:
    """HTTP request spans are emitted using the domain-scoped tracer."""

    def test_http_span_emitted_on_request(self, test_domain, span_exporter):
        """An HTTP span is created for each instrumented request."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain)
        client = TestClient(app)

        client.post("/orders")

        spans = span_exporter.get_finished_spans()
        # FastAPI instrumentor creates a root span with HTTP method + route
        root_http = _find_root_http_span(spans)
        assert root_http.name.startswith("POST")

    def test_http_span_has_route_attribute(self, test_domain, span_exporter):
        """HTTP spans carry the http.route attribute."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain)
        client = TestClient(app)

        client.post("/orders")

        spans = span_exporter.get_finished_spans()
        http_span = _find_root_http_span(spans)
        assert http_span.attributes.get("http.route") == "/orders"

    def test_http_span_has_status_code(self, test_domain, span_exporter):
        """HTTP spans carry the status code attribute."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain)
        client = TestClient(app)

        client.post("/orders")

        spans = span_exporter.get_finished_spans()
        http_span = _find_root_http_span(spans)
        # The attribute name depends on OTEL semantic conventions version
        status = http_span.attributes.get(
            "http.status_code"
        ) or http_span.attributes.get("http.response.status_code")
        assert status == 200


# ---------------------------------------------------------------------------
# Tests: HTTP span → command span parent-child relationship
# ---------------------------------------------------------------------------


class TestSpanParenting:
    """HTTP spans automatically parent command processing spans."""

    def test_command_span_is_child_of_http_span(self, test_domain, span_exporter):
        """protean.command.process span has the HTTP span as its parent."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain)
        client = TestClient(app)

        client.post("/orders")

        spans = span_exporter.get_finished_spans()
        http_span = _find_root_http_span(spans)
        command_span = next(s for s in spans if s.name == "protean.command.process")

        # The command span's parent should be the HTTP span
        assert command_span.parent is not None
        assert command_span.parent.span_id == http_span.context.span_id

    def test_handler_span_shares_trace_id_with_http_span(
        self, test_domain, span_exporter
    ):
        """All spans in the request share the same trace ID."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain)
        client = TestClient(app)

        client.post("/orders")

        spans = span_exporter.get_finished_spans()
        http_span = _find_root_http_span(spans)
        trace_id = http_span.context.trace_id

        # Every span should share the same trace ID
        for span in spans:
            assert span.context.trace_id == trace_id, (
                f"Span '{span.name}' has different trace_id"
            )

    def test_full_span_tree(self, test_domain, span_exporter):
        """Verify the complete span tree: HTTP → command.process → handler."""
        test_domain.config["telemetry"]["enabled"] = True
        app = _make_app(test_domain)
        client = TestClient(app)

        client.post("/orders")

        spans = span_exporter.get_finished_spans()
        span_names = {s.name for s in spans}

        # Expected spans present
        assert any(n.startswith("POST") for n in span_names)
        assert "protean.command.process" in span_names
        assert "protean.handler.execute" in span_names

        # command.process → its parent is the HTTP span
        command_span = next(s for s in spans if s.name == "protean.command.process")
        http_span = _find_root_http_span(spans)
        assert command_span.parent.span_id == http_span.context.span_id

        # handler.execute → its parent is command.process
        handler_span = next(s for s in spans if s.name == "protean.handler.execute")
        assert handler_span.parent.span_id == command_span.context.span_id


# ---------------------------------------------------------------------------
# Tests: Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """instrument_app degrades gracefully when packages are missing."""

    def test_no_op_when_telemetry_disabled(self, test_domain):
        """No instrumentation when telemetry.enabled is False."""
        test_domain.config["telemetry"]["enabled"] = False
        app = FastAPI()
        result = instrument_app(app, test_domain)
        assert result is False
        assert not getattr(app, "_is_instrumented_by_opentelemetry", False)

    def test_no_op_when_instrumentor_missing(self, test_domain, monkeypatch):
        """Returns False when opentelemetry-instrumentation-fastapi is missing."""
        test_domain.config["telemetry"]["enabled"] = True
        test_domain._otel_init_attempted = True

        # Simulate import failure by patching the import
        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def mock_import(name, *args, **kwargs):
            if "opentelemetry.instrumentation.fastapi" in name:
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        app = FastAPI()
        result = instrument_app(app, test_domain)
        assert result is False

    def test_initializes_telemetry_if_not_attempted(self, test_domain):
        """Ensures init_telemetry is called when not yet attempted."""
        test_domain.config["telemetry"]["enabled"] = True
        # Don't set _otel_init_attempted, so instrument_app should trigger init
        assert not getattr(test_domain, "_otel_init_attempted", False)

        app = FastAPI()
        # This will attempt to init, which may fail without a real exporter
        # but the init_attempted flag should be set
        instrument_app(app, test_domain)
        assert getattr(test_domain, "_otel_init_attempted", False)

    def test_instruments_without_providers(self, test_domain):
        """Instruments when enabled but providers are None (edge case)."""
        test_domain.config["telemetry"]["enabled"] = True
        test_domain._otel_init_attempted = True
        # Explicitly set providers to None
        test_domain._otel_tracer_provider = None
        test_domain._otel_meter_provider = None

        app = FastAPI()
        result = instrument_app(app, test_domain)
        assert result is True
