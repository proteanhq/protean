"""OpenTelemetry integration for Protean domains.

All OTEL interaction is funneled through this module. The rest of
the codebase never imports ``opentelemetry`` directly.

When the ``opentelemetry`` packages are not installed or telemetry
is disabled, every public function gracefully returns a no-op tracer
or meter, so instrumentation code never needs conditional guards.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detect whether the OpenTelemetry SDK is available
# ---------------------------------------------------------------------------

_OTEL_AVAILABLE = False

try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

_TRACER_PROVIDER_KEY = "_otel_tracer_provider"
_METER_PROVIDER_KEY = "_otel_meter_provider"
_TELEMETRY_INIT_KEY = "_otel_init_attempted"


def init_telemetry(domain: Domain) -> Any:
    """Initialize TracerProvider and MeterProvider from domain config.

    Returns the ``TracerProvider`` when telemetry is enabled, ``None``
    otherwise.  Marks the domain so initialization is only attempted once.
    """
    # Mark that init was attempted so Domain properties don't retry
    setattr(domain, _TELEMETRY_INIT_KEY, True)

    config = domain.config.get("telemetry", {})
    if not config.get("enabled", False):
        return None

    if not _OTEL_AVAILABLE:
        logger.warning(
            "Telemetry is enabled but opentelemetry packages are not installed. "
            "Install with: pip install protean[telemetry]"
        )
        return None

    service_name = config.get("service_name") or domain.normalized_name
    resource_attrs: dict[str, Any] = {
        "service.name": service_name,
    }
    resource_attrs.update(config.get("resource_attributes", {}))
    resource = Resource.create(resource_attrs)

    # --- Tracer Provider ---------------------------------------------------
    tracer_provider = SDKTracerProvider(resource=resource)

    exporter = _build_span_exporter(config)
    if exporter is not None:
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    # --- Meter Provider ----------------------------------------------------
    metric_reader = _build_metric_reader(config)
    meter_provider = SDKMeterProvider(
        resource=resource,
        metric_readers=[metric_reader] if metric_reader else [],
    )

    # Stash on the domain for later shutdown — get_tracer()/get_meter()
    # resolve from these domain-scoped providers rather than relying on
    # the OTEL global, which is single-assignment.
    setattr(domain, _TRACER_PROVIDER_KEY, tracer_provider)
    setattr(domain, _METER_PROVIDER_KEY, meter_provider)

    logger.info(
        "OpenTelemetry initialized for domain '%s' (exporter=%s)",
        domain.name,
        config.get("exporter", "otlp"),
    )
    return tracer_provider


def get_tracer(domain: Domain, name: str = "protean") -> Any:
    """Return a configured ``Tracer``, or a no-op tracer."""
    if not _OTEL_AVAILABLE:
        return _NoOpTracer()

    provider = getattr(domain, _TRACER_PROVIDER_KEY, None)
    if provider is None:
        # Return an OTEL no-op tracer
        return otel_trace.get_tracer(name)

    return provider.get_tracer(name)


def get_meter(domain: Domain, name: str = "protean") -> Any:
    """Return a configured ``Meter``, or a no-op meter."""
    if not _OTEL_AVAILABLE:
        return _NoOpMeter()

    provider = getattr(domain, _METER_PROVIDER_KEY, None)
    if provider is None:
        return otel_metrics.get_meter(name)

    return provider.get_meter(name)


def shutdown_telemetry(domain: Domain) -> None:
    """Flush and shutdown providers attached to *domain*."""
    tracer_provider = getattr(domain, _TRACER_PROVIDER_KEY, None)
    if tracer_provider is not None and hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()
        setattr(domain, _TRACER_PROVIDER_KEY, None)

    meter_provider = getattr(domain, _METER_PROVIDER_KEY, None)
    if meter_provider is not None and hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()
        setattr(domain, _METER_PROVIDER_KEY, None)

    # Reset the init sentinel so telemetry can be re-initialized if needed
    setattr(domain, _TELEMETRY_INIT_KEY, False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_span_exporter(config: dict[str, Any]) -> Any:
    """Build a span exporter from config. Returns ``None`` on failure."""
    exporter_name = config.get("exporter", "otlp")
    endpoint = config.get("endpoint")

    if exporter_name == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            kwargs: dict[str, Any] = {}
            if endpoint:
                kwargs["endpoint"] = endpoint
            return OTLPSpanExporter(**kwargs)
        except ImportError:
            logger.warning(
                "OTLP exporter requested but opentelemetry-exporter-otlp-proto-grpc "
                "is not installed. No spans will be exported."
            )
            return None
    elif exporter_name == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()

    logger.warning("Unknown telemetry exporter '%s'. No spans will be exported.", exporter_name)
    return None


def _build_metric_reader(config: dict[str, Any]) -> Any:
    """Build a metric reader from config. Returns ``None`` on failure."""
    exporter_name = config.get("exporter", "otlp")

    if exporter_name == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )

            endpoint = config.get("endpoint")
            kwargs: dict[str, Any] = {}
            if endpoint:
                kwargs["endpoint"] = endpoint
            return PeriodicExportingMetricReader(OTLPMetricExporter(**kwargs))
        except ImportError:
            logger.warning(
                "OTLP metric exporter requested but opentelemetry-exporter-otlp-proto-grpc "
                "is not installed. No metrics will be exported."
            )
            return None
    elif exporter_name == "console":
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader as _PeriodicReader,
        )

        return _PeriodicReader(ConsoleMetricExporter())

    logger.warning("Unknown telemetry exporter '%s'. No metrics will be exported.", exporter_name)
    return None


# ---------------------------------------------------------------------------
# Lightweight no-op fallbacks (used when OTEL is not installed)
# ---------------------------------------------------------------------------


class _NoOpSpan:
    """Minimal no-op span that supports the context-manager protocol."""

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def record_exception(self, exception: BaseException, **kwargs: Any) -> None:
        pass

    def end(self) -> None:
        pass

    @property
    def is_recording(self) -> bool:
        return False


class _NoOpTracer:
    """Minimal no-op tracer returned when OTEL is not installed."""

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()


class _NoOpCounter:
    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        pass


class _NoOpHistogram:
    def record(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        pass


class _NoOpMeter:
    """Minimal no-op meter returned when OTEL is not installed."""

    def create_counter(self, name: str, **kwargs: Any) -> _NoOpCounter:
        return _NoOpCounter()

    def create_histogram(self, name: str, **kwargs: Any) -> _NoOpHistogram:
        return _NoOpHistogram()

    def create_up_down_counter(self, name: str, **kwargs: Any) -> _NoOpCounter:
        return _NoOpCounter()
