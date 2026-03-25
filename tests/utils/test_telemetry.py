"""Tests for OpenTelemetry integration in utils/telemetry.py."""

from unittest.mock import patch

import pytest

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from protean.utils.telemetry import (
    _NoOpMeter,
    _NoOpTracer,
    get_meter,
    get_tracer,
    init_telemetry,
    shutdown_telemetry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_otel_globals():
    """Reset OTEL global providers between tests to prevent cross-test leakage.

    OpenTelemetry globals are typically single-assignment; we use internal
    reset helpers to ensure each test starts with a clean slate.
    """
    yield
    # Reset the global tracer and meter providers to their defaults.
    # The internal attributes vary across OTEL versions; access them safely.
    if hasattr(otel_trace, "_TRACER_PROVIDER_SET_ONCE"):
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    otel_trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]

    from opentelemetry.metrics import _internal as metrics_internal

    if hasattr(metrics_internal, "_METER_PROVIDER_SET_ONCE"):
        metrics_internal._METER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    metrics_internal._METER_PROVIDER = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enable_telemetry(domain, **overrides):
    """Enable telemetry on a test domain with optional config overrides."""
    telemetry_config = {"enabled": True, **overrides}
    domain.config["telemetry"] = {
        **domain.config.get("telemetry", {}),
        **telemetry_config,
    }


def _init_with_in_memory(domain):
    """Initialize telemetry with in-memory exporters for testing.

    Returns (tracer_provider, span_exporter, metric_reader) so tests can
    inspect captured spans and metrics.  Providers are stashed on the domain
    just like ``init_telemetry`` does, but without touching OTEL globals.
    """
    from opentelemetry.sdk.resources import Resource

    service_name = (
        domain.config.get("telemetry", {}).get("service_name") or domain.normalized_name
    )
    resource = Resource.create({"service.name": service_name})

    # Tracer with in-memory exporter
    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    # Meter with in-memory reader
    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    # Stash on domain (same keys as init_telemetry uses)
    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return tracer_provider, span_exporter, metric_reader


# ---------------------------------------------------------------------------
# Tests: Disabled / No-op behaviour
# ---------------------------------------------------------------------------


class TestTelemetryDisabled:
    """Telemetry disabled (default) — everything should be a no-op."""

    def test_init_returns_none_when_disabled(self, test_domain):
        result = init_telemetry(test_domain)
        assert result is None

    def test_get_tracer_returns_object_when_disabled(self, test_domain):
        tracer = get_tracer(test_domain)
        assert tracer is not None

    def test_get_meter_returns_object_when_disabled(self, test_domain):
        meter = get_meter(test_domain)
        assert meter is not None

    def test_shutdown_is_safe_when_never_initialized(self, test_domain):
        # Should not raise
        shutdown_telemetry(test_domain)

    def test_default_config_has_telemetry_disabled(self, test_domain):
        telemetry_config = test_domain.config.get("telemetry", {})
        assert telemetry_config.get("enabled") is False


# ---------------------------------------------------------------------------
# Tests: Enabled with in-memory exporters
# ---------------------------------------------------------------------------


class TestTelemetryEnabled:
    """Telemetry enabled with in-memory exporters for span/metric verification."""

    def test_init_creates_tracer_provider(self, test_domain):
        _enable_telemetry(test_domain)
        tracer_provider, _, _ = _init_with_in_memory(test_domain)

        assert isinstance(tracer_provider, SDKTracerProvider)
        assert test_domain._otel_tracer_provider is tracer_provider

    def test_init_creates_meter_provider(self, test_domain):
        _enable_telemetry(test_domain)
        _init_with_in_memory(test_domain)

        assert isinstance(test_domain._otel_meter_provider, SDKMeterProvider)

    def test_get_tracer_returns_functional_tracer(self, test_domain):
        _enable_telemetry(test_domain)
        _, span_exporter, _ = _init_with_in_memory(test_domain)

        tracer = get_tracer(test_domain)
        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("test.key", "test-value")

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "test-span"
        assert spans[0].attributes["test.key"] == "test-value"

    def test_get_meter_returns_functional_meter(self, test_domain):
        _enable_telemetry(test_domain)
        _, _, metric_reader = _init_with_in_memory(test_domain)

        meter = get_meter(test_domain)
        counter = meter.create_counter("test.counter", description="A test counter")
        counter.add(42, {"env": "test"})

        metrics_data = metric_reader.get_metrics_data()
        assert metrics_data is not None
        # Verify we have at least one resource metric with our counter
        resource_metrics = metrics_data.resource_metrics
        assert len(resource_metrics) > 0

    def test_shutdown_clears_providers(self, test_domain):
        _enable_telemetry(test_domain)
        _init_with_in_memory(test_domain)

        assert test_domain._otel_tracer_provider is not None
        assert test_domain._otel_meter_provider is not None

        shutdown_telemetry(test_domain)

        assert test_domain._otel_tracer_provider is None
        assert test_domain._otel_meter_provider is None

    def test_shutdown_is_idempotent(self, test_domain):
        _enable_telemetry(test_domain)
        _init_with_in_memory(test_domain)

        shutdown_telemetry(test_domain)
        # Second call should not raise
        shutdown_telemetry(test_domain)


# ---------------------------------------------------------------------------
# Tests: Configuration parsing
# ---------------------------------------------------------------------------


class TestTelemetryConfig:
    """Verify telemetry configuration is correctly parsed."""

    def test_default_exporter_is_otlp(self, test_domain):
        telemetry_config = test_domain.config.get("telemetry", {})
        assert telemetry_config.get("exporter") == "otlp"

    def test_default_service_name_is_none(self, test_domain):
        telemetry_config = test_domain.config.get("telemetry", {})
        assert telemetry_config.get("service_name") is None

    def test_service_name_defaults_to_domain_name(self, test_domain):
        _enable_telemetry(test_domain)
        _, span_exporter, _ = _init_with_in_memory(test_domain)

        tracer = get_tracer(test_domain)
        with tracer.start_as_current_span("check-resource"):
            pass

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        resource_attrs = dict(spans[0].resource.attributes)
        assert resource_attrs["service.name"] == test_domain.normalized_name

    def test_custom_service_name(self, test_domain):
        _enable_telemetry(test_domain, service_name="my-custom-service")
        _, span_exporter, _ = _init_with_in_memory(test_domain)

        tracer = get_tracer(test_domain)
        with tracer.start_as_current_span("check-resource"):
            pass

        spans = span_exporter.get_finished_spans()
        resource_attrs = dict(spans[0].resource.attributes)
        assert resource_attrs["service.name"] == "my-custom-service"

    def test_custom_resource_attributes(self, test_domain):
        _enable_telemetry(
            test_domain,
            resource_attributes={"deployment.environment": "staging"},
        )

        from opentelemetry.sdk.resources import Resource

        config = test_domain.config.get("telemetry", {})
        resource_attrs = {"service.name": test_domain.normalized_name}
        resource_attrs.update(config.get("resource_attributes", {}))
        resource = Resource.create(resource_attrs)

        attrs = dict(resource.attributes)
        assert attrs["deployment.environment"] == "staging"

    def test_endpoint_defaults_to_none(self, test_domain):
        telemetry_config = test_domain.config.get("telemetry", {})
        assert telemetry_config.get("endpoint") is None

    def test_resource_attributes_defaults_to_empty(self, test_domain):
        telemetry_config = test_domain.config.get("telemetry", {})
        assert telemetry_config.get("resource_attributes") == {}


# ---------------------------------------------------------------------------
# Tests: Domain integration (tracer/meter properties)
# ---------------------------------------------------------------------------


class TestDomainIntegration:
    """Verify Domain.tracer and Domain.meter properties."""

    def test_domain_tracer_property_returns_tracer(self, test_domain):
        _enable_telemetry(test_domain)
        _init_with_in_memory(test_domain)

        tracer = test_domain.tracer
        assert tracer is not None

    def test_domain_meter_property_returns_meter(self, test_domain):
        _enable_telemetry(test_domain)
        _init_with_in_memory(test_domain)

        meter = test_domain.meter
        assert meter is not None

    def test_domain_tracer_property_noop_when_disabled(self, test_domain):
        # Telemetry disabled by default
        tracer = test_domain.tracer
        assert tracer is not None
        # Should support the span context manager protocol without error
        with tracer.start_as_current_span("noop-span"):
            pass

    def test_domain_meter_property_noop_when_disabled(self, test_domain):
        meter = test_domain.meter
        assert meter is not None
        # Should support counter creation without error
        counter = meter.create_counter("noop.counter")
        counter.add(1)

    def test_init_attempted_only_once(self, test_domain):
        """Verify init_telemetry is not called on every property access."""
        # First access triggers init
        _ = test_domain.tracer
        assert test_domain._otel_init_attempted is True

        # Patch init_telemetry to track if it's called again
        with patch("protean.utils.telemetry.init_telemetry") as mock_init:
            _ = test_domain.tracer
            _ = test_domain.meter
            mock_init.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: No-op fallbacks
# ---------------------------------------------------------------------------


class TestNoOpFallbacks:
    """Verify the lightweight no-op classes work correctly."""

    def test_noop_tracer_start_span(self):
        tracer = _NoOpTracer()
        span = tracer.start_span("test")
        assert span.is_recording is False
        span.set_attribute("key", "value")
        span.end()

    def test_noop_tracer_context_manager(self):
        tracer = _NoOpTracer()
        with tracer.start_as_current_span("test") as span:
            span.set_attribute("key", "value")
            span.set_status("OK")
            span.record_exception(ValueError("test"))

    def test_noop_meter_counter(self):
        meter = _NoOpMeter()
        counter = meter.create_counter("test.counter")
        counter.add(1)
        counter.add(5, {"env": "test"})

    def test_noop_meter_histogram(self):
        meter = _NoOpMeter()
        histogram = meter.create_histogram("test.histogram")
        histogram.record(100)
        histogram.record(200, {"env": "test"})

    def test_noop_meter_up_down_counter(self):
        meter = _NoOpMeter()
        counter = meter.create_up_down_counter("test.gauge")
        counter.add(1)
        counter.add(-1)


# ---------------------------------------------------------------------------
# Tests: Graceful degradation when OTEL not installed
# ---------------------------------------------------------------------------


class TestOtelNotInstalled:
    """Verify graceful no-op when opentelemetry packages are missing."""

    def test_get_tracer_returns_noop_when_otel_unavailable(self, test_domain):
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            tracer = get_tracer(test_domain)
            assert isinstance(tracer, _NoOpTracer)

    def test_get_meter_returns_noop_when_otel_unavailable(self, test_domain):
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            meter = get_meter(test_domain)
            assert isinstance(meter, _NoOpMeter)

    def test_init_returns_none_when_otel_unavailable(self, test_domain):
        _enable_telemetry(test_domain)
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            result = init_telemetry(test_domain)
            assert result is None

    def test_shutdown_safe_when_otel_unavailable(self, test_domain):
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            shutdown_telemetry(test_domain)


# ---------------------------------------------------------------------------
# Tests: init_telemetry with real config (console exporter, no network)
# ---------------------------------------------------------------------------


class TestInitTelemetryConsoleExporter:
    """Test init_telemetry with console exporter (no network dependency)."""

    def test_init_with_console_exporter(self, test_domain):
        _enable_telemetry(test_domain, exporter="console")
        result = init_telemetry(test_domain)

        assert isinstance(result, SDKTracerProvider)
        assert test_domain._otel_tracer_provider is result
        assert test_domain._otel_meter_provider is not None

        # Cleanup
        shutdown_telemetry(test_domain)

    def test_init_with_unknown_exporter(self, test_domain):
        _enable_telemetry(test_domain, exporter="unknown_exporter")
        result = init_telemetry(test_domain)

        # Should still create providers, just without exporters
        assert isinstance(result, SDKTracerProvider)

        shutdown_telemetry(test_domain)

    def test_shutdown_resets_init_sentinel(self, test_domain):
        """Verify shutdown resets the init sentinel for re-initialization."""
        _enable_telemetry(test_domain, exporter="console")
        init_telemetry(test_domain)
        assert test_domain._otel_init_attempted is True

        shutdown_telemetry(test_domain)
        assert test_domain._otel_init_attempted is False
