"""The examples on the OpenTelemetry guide behave as the page says."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from protean.utils.telemetry import get_tracer_provider, shutdown_telemetry
from tests.docs.support import load_example

# The module imports FastAPI, so every test in it needs the extra.
pytestmark = [pytest.mark.no_test_domain, pytest.mark.fastapi]


def capture_spans(domain) -> InMemorySpanExporter:
    """Attach an in-memory exporter to the provider the domain built from its config."""
    # Reading domain.tracer builds the providers from config on first use, the
    # same way command processing does in a running app.
    domain.tracer
    provider = get_tracer_provider(domain)
    assert provider is not None
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def spans_named(exporter, name):
    return [span for span in exporter.get_finished_spans() if span.name == name]


def server_spans(exporter):
    return [
        span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER
    ]


@pytest.fixture
def otel_example():
    """Load an example and shut its telemetry providers down afterwards."""
    loaded = []

    def load(module):
        loaded.append(module)
        module.domain.init(traverse=False)
        return module

    yield load
    for module in loaded:
        shutdown_telemetry(module.domain)


def test_instrumented_app_uses_the_configured_service_name(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/001.py"))

    provider = get_tracer_provider(example.domain)

    assert provider is not None
    assert provider.resource.attributes["service.name"] == "orders-api"


def test_http_span_parents_the_command_and_handler_spans(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/001.py"))
    exporter = capture_spans(example.domain)

    response = TestClient(example.app).post(
        "/orders", json={"customer": "Ada", "total": 42.0}
    )
    assert response.status_code == 201

    [http_span] = server_spans(exporter)
    [process_span] = spans_named(exporter, "protean.command.process")
    [handler_span] = spans_named(exporter, "protean.handler.execute")

    assert http_span.attributes["http.route"] == "/orders"
    assert http_span.attributes["http.status_code"] == 201
    assert process_span.parent.span_id == http_span.context.span_id
    assert process_span.context.trace_id == http_span.context.trace_id
    assert process_span.attributes["protean.command.type"] == "Orders.PlaceOrder.v1"
    assert handler_span.parent.span_id == process_span.context.span_id
    assert handler_span.attributes["protean.handler.name"] == "OrderCommandHandler"


def test_instrumenting_the_same_app_twice_is_skipped(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/001.py"))

    assert example.instrument_app(example.app, example.domain) is False


def test_instrument_app_does_nothing_when_telemetry_is_disabled(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/001.py"))
    example.domain.config["telemetry"]["enabled"] = False

    assert example.instrument_app(FastAPI(), example.domain) is False


def test_excluded_health_paths_produce_no_spans(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/002.py"))
    exporter = capture_spans(example.domain)
    client = TestClient(example.app)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert server_spans(exporter) == []

    assert client.get("/orders").status_code == 200
    [span] = server_spans(exporter)
    assert span.attributes["http.route"] == "/orders"


def test_excluded_observatory_paths_produce_no_spans(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/003.py"))
    exporter = capture_spans(example.domain)
    client = TestClient(example.app)

    assert client.get("/metrics").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert server_spans(exporter) == []

    assert client.get("/api/orders").status_code == 200
    [span] = server_spans(exporter)
    assert span.attributes["http.route"] == "/api/orders"


def test_span_pattern_records_the_attribute_and_leaves_status_unset(otel_example):
    example = otel_example(load_example("guides/server/opentelemetry/004.py"))
    exporter = capture_spans(example.domain)

    assert example.cache_get("sku-1") == "Blue mug"

    [span] = spans_named(exporter, "protean.cache.get")
    assert span.attributes["protean.cache.key"] == "sku-1"
    assert span.status.status_code == StatusCode.UNSET
    assert span.events == ()


def test_span_pattern_marks_the_span_as_an_error_through_set_span_error(
    otel_example,
):
    example = otel_example(load_example("guides/server/opentelemetry/004.py"))
    exporter = capture_spans(example.domain)

    with pytest.raises(KeyError):
        example.cache_get("sku-404")

    [span] = spans_named(exporter, "protean.cache.get")
    assert span.status.status_code == StatusCode.ERROR
    assert "sku-404" in span.status.description
    exception_events = [event for event in span.events if event.name == "exception"]
    assert len(exception_events) == 1
    assert exception_events[0].attributes["exception.type"] == "KeyError"
