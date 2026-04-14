"""Tests for OpenTelemetry trace-context injection into log records.

Verifies that:
- ``protean_otel_processor`` adds ``trace_id`` / ``span_id`` / ``trace_flags``
  to structlog event dicts when a span is active.
- ``OTelTraceContextFilter`` sets the same attributes on stdlib
  ``LogRecord`` objects.
- Both integrations are safe no-ops outside any span and when the
  ``opentelemetry`` package is not importable.
- ``Domain.configure_logging()`` wires the filter and processor only when
  ``telemetry.enabled=True``.
- ``ProteanCorrelationFilter`` / ``protean_correlation_processor`` fall
  back to ``g.correlation_id`` when no ``g.message_in_context`` is set,
  and message-based extraction still wins when both are present.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest
import structlog
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean import Domain
from protean.integrations.logging import (
    OTelTraceContextFilter,
    ProteanCorrelationFilter,
    protean_correlation_processor,
    protean_otel_processor,
)
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import g


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _clear_root_logger() -> None:
    """Reset root logger state, removing pytest's LogCaptureHandler too."""
    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()
    root.setLevel(logging.WARNING)


@pytest.fixture
def tracer_provider() -> Iterator[SDKTracerProvider]:
    """Provide an isolated TracerProvider with in-memory exporter per test.

    Follows the same reset pattern as ``tests/utils/test_telemetry.py``:
    install the provider up front and reset OTEL globals only in teardown
    so each test starts with a clean slate.
    """
    resource = Resource.create({"service.name": "test"})
    provider = SDKTracerProvider(resource=resource)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)

    try:
        yield provider
    finally:
        if hasattr(otel_trace, "_TRACER_PROVIDER_SET_ONCE"):
            otel_trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
        otel_trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# protean_otel_processor
# ---------------------------------------------------------------------------


class TestOTelProcessor:
    @pytest.mark.no_test_domain
    def test_processor_injects_trace_context_inside_span(
        self, tracer_provider: SDKTracerProvider
    ) -> None:
        tracer = tracer_provider.get_tracer("test")
        with tracer.start_as_current_span("test-span"):
            event_dict = protean_otel_processor(None, "info", {"event": "msg"})

        assert isinstance(event_dict["trace_id"], str)
        assert len(event_dict["trace_id"]) == 32
        assert isinstance(event_dict["span_id"], str)
        assert len(event_dict["span_id"]) == 16
        assert isinstance(event_dict["trace_flags"], int)

    @pytest.mark.no_test_domain
    def test_processor_empty_outside_span(self) -> None:
        event_dict = protean_otel_processor(None, "info", {"event": "msg"})
        assert event_dict["trace_id"] == ""
        assert event_dict["span_id"] == ""
        assert event_dict["trace_flags"] == 0

    @pytest.mark.no_test_domain
    def test_processor_safe_when_opentelemetry_missing(self) -> None:
        """When opentelemetry is unavailable, processor returns empty fields.

        Simulates ``opentelemetry`` being uninstalled by nulling the
        module-level binding the processor resolves at import time.
        """
        with patch(
            "protean.integrations.logging._get_current_span",
            None,
        ):
            event_dict = protean_otel_processor(None, "info", {"event": "msg"})

        assert event_dict["trace_id"] == ""
        assert event_dict["span_id"] == ""
        assert event_dict["trace_flags"] == 0


# ---------------------------------------------------------------------------
# OTelTraceContextFilter
# ---------------------------------------------------------------------------


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )


class TestOTelFilter:
    @pytest.mark.no_test_domain
    def test_filter_injects_on_log_record(
        self, tracer_provider: SDKTracerProvider
    ) -> None:
        filt = OTelTraceContextFilter()
        tracer = tracer_provider.get_tracer("test")
        record = _make_record()
        with tracer.start_as_current_span("test-span"):
            assert filt.filter(record) is True

        assert len(record.trace_id) == 32  # type: ignore[attr-defined]
        assert len(record.span_id) == 16  # type: ignore[attr-defined]
        assert isinstance(record.trace_flags, int)  # type: ignore[attr-defined]

    @pytest.mark.no_test_domain
    def test_filter_empty_outside_span(self) -> None:
        filt = OTelTraceContextFilter()
        record = _make_record()

        assert filt.filter(record) is True
        assert record.trace_id == ""  # type: ignore[attr-defined]
        assert record.span_id == ""  # type: ignore[attr-defined]
        assert record.trace_flags == 0  # type: ignore[attr-defined]

    @pytest.mark.no_test_domain
    def test_filter_safe_when_opentelemetry_missing(self) -> None:
        """When opentelemetry is unavailable, filter sets empty fields."""
        filt = OTelTraceContextFilter()
        record = _make_record()

        with patch(
            "protean.integrations.logging._get_current_span",
            None,
        ):
            result = filt.filter(record)

        assert result is True
        assert record.trace_id == ""  # type: ignore[attr-defined]
        assert record.span_id == ""  # type: ignore[attr-defined]
        assert record.trace_flags == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Domain.configure_logging wiring
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDomainConfigureLoggingOTel:
    """``Domain.configure_logging()`` conditionally wires OTel injection."""

    def setup_method(self) -> None:
        structlog.reset_defaults()
        _clear_root_logger()

    def teardown_method(self) -> None:
        _clear_root_logger()
        structlog.reset_defaults()

    def test_wires_otel_when_telemetry_enabled(
        self, tracer_provider: SDKTracerProvider
    ) -> None:
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestOTelOn",
            config={"telemetry": {"enabled": True}},
        )
        _clear_root_logger()
        domain.configure_logging(level="DEBUG")

        root = logging.getLogger()
        assert any(isinstance(f, OTelTraceContextFilter) for f in root.filters)

        # The structlog pipeline must also carry the otel processor so
        # ``get_logger().info(...)`` events end up with trace context.
        assert protean_otel_processor in structlog.get_config()["processors"]

        # Emit a stdlib log inside a span and verify the filter injected
        # trace context onto the record.
        captured: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _Capture(level=logging.DEBUG)
        for f in root.filters:
            handler.addFilter(f)
        root.addHandler(handler)
        # Override the WARNING default for ``myapp.*`` to ensure INFO is captured.
        app_logger = logging.getLogger("myapp.test")
        app_logger.setLevel(logging.DEBUG)

        tracer = tracer_provider.get_tracer("test")
        try:
            with tracer.start_as_current_span("test-span"):
                app_logger.info("hello")
        finally:
            root.removeHandler(handler)

        assert len(captured) >= 1
        rec = captured[-1]
        assert getattr(rec, "trace_id", "") != ""
        assert len(rec.trace_id) == 32  # type: ignore[attr-defined]
        assert len(rec.span_id) == 16  # type: ignore[attr-defined]

    def test_skips_otel_when_telemetry_disabled(self) -> None:
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestOTelOff",
            config={"telemetry": {"enabled": False}},
        )
        _clear_root_logger()
        domain.configure_logging()

        root = logging.getLogger()
        assert not any(isinstance(f, OTelTraceContextFilter) for f in root.filters)

        # The otel processor must not be registered when telemetry is disabled,
        # avoiding the lazy ``opentelemetry`` import on every log call.
        assert protean_otel_processor not in structlog.get_config()["processors"]

    def test_does_not_duplicate_filter_on_repeated_configure(
        self, tracer_provider: SDKTracerProvider
    ) -> None:
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestOTelIdempotent",
            config={"telemetry": {"enabled": True}},
        )
        _clear_root_logger()
        domain.configure_logging()
        domain.configure_logging()

        root = logging.getLogger()
        otel_filters = [
            f for f in root.filters if isinstance(f, OTelTraceContextFilter)
        ]
        assert len(otel_filters) == 1


# ---------------------------------------------------------------------------
# ProteanCorrelationFilter / processor — g.correlation_id fallback
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_g() -> Iterator[None]:
    """Clear ``g`` attributes touched by the fallback tests, even on failure."""
    for key in ("message_in_context", "correlation_id", "causation_id"):
        g.pop(key, None)
    try:
        yield
    finally:
        for key in ("message_in_context", "correlation_id", "causation_id"):
            g.pop(key, None)


class TestCorrelationFallbackToG:
    """Correlation extraction falls back to ``g.correlation_id`` / ``g.causation_id``."""

    def test_filter_falls_back_to_g_correlation_id(self, test_domain, clean_g) -> None:
        g.correlation_id = "manual-abc"
        g.causation_id = "manual-xyz"

        filt = ProteanCorrelationFilter()
        record = _make_record()
        filt.filter(record)

        assert record.correlation_id == "manual-abc"  # type: ignore[attr-defined]
        assert record.causation_id == "manual-xyz"  # type: ignore[attr-defined]

    def test_processor_falls_back_to_g_correlation_id(
        self, test_domain, clean_g
    ) -> None:
        g.correlation_id = "proc-corr"
        g.causation_id = "proc-cause"

        event_dict = protean_correlation_processor(None, "info", {"event": "hi"})

        assert event_dict["correlation_id"] == "proc-corr"
        assert event_dict["causation_id"] == "proc-cause"

    def test_message_takes_precedence_over_g_correlation_id(
        self, test_domain, clean_g
    ) -> None:
        g.correlation_id = "fallback-corr"
        g.causation_id = "fallback-cause"

        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-1", type="Test.Cmd.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="msg-corr",
                    causation_id="msg-cause",
                ),
            ),
        )
        g.message_in_context = msg

        filt = ProteanCorrelationFilter()
        record = _make_record()
        filt.filter(record)

        assert record.correlation_id == "msg-corr"  # type: ignore[attr-defined]
        assert record.causation_id == "msg-cause"  # type: ignore[attr-defined]

    def test_fallback_missing_g_fields_are_empty(self, test_domain, clean_g) -> None:
        """When neither message nor g fields are set, filter yields empty strings."""

        filt = ProteanCorrelationFilter()
        record = _make_record()
        filt.filter(record)

        assert record.correlation_id == ""  # type: ignore[attr-defined]
        assert record.causation_id == ""  # type: ignore[attr-defined]
