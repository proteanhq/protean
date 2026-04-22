"""Automatic correlation and trace context injection for Python logging.

Provides stdlib ``logging.Filter`` classes and ``structlog`` processors that
read the active domain context (``g.message_in_context`` or ``g.correlation_id``)
and the active OpenTelemetry span, then inject ``correlation_id``,
``causation_id``, ``trace_id``, ``span_id``, and ``trace_flags`` into every
log record — zero boilerplate required.

Typical usage with stdlib logging::

    import logging
    from protean.integrations.logging import (
        ProteanCorrelationFilter,
        OTelTraceContextFilter,
    )

    handler = logging.StreamHandler()
    handler.addFilter(ProteanCorrelationFilter())
    handler.addFilter(OTelTraceContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(message)s correlation_id=%(correlation_id)s trace_id=%(trace_id)s"
        )
    )
    logging.getLogger().addHandler(handler)

Typical usage with structlog::

    import structlog
    from protean.integrations.logging import (
        protean_correlation_processor,
        protean_otel_processor,
    )

    structlog.configure(
        processors=[
            protean_correlation_processor,
            protean_otel_processor,
            structlog.dev.ConsoleRenderer(),
        ]
    )

All integrations are safe to use when no domain context, no active span, or
no ``opentelemetry`` installation exists — they silently fall back to empty
strings (or ``0`` for ``trace_flags``).
"""

import logging
from typing import Any, Callable, Iterable, Optional

# OpenTelemetry trace helpers are resolved lazily on first use so that merely
# importing this module (e.g. from ``Domain.configure_logging``) does not
# trigger the ``opentelemetry`` import when telemetry is disabled. After the
# first call the module-level slots act as a cache, keeping the hot path a
# pure attribute lookup — no repeated ``from ... import`` on every log record.
_OTEL_UNLOADED = object()  # sentinel: helpers have not been resolved yet
_get_current_span: Any = _OTEL_UNLOADED
_format_trace_id: Any = _OTEL_UNLOADED
_format_span_id: Any = _OTEL_UNLOADED


def _load_otel_helpers() -> None:
    """Populate the module-level OTel trace helper slots.

    Called on the first access from :func:`_get_otel_trace_context`. Sets the
    slots to ``None`` when ``opentelemetry`` is not installed, so subsequent
    calls short-circuit without re-attempting the import.
    """
    global _get_current_span, _format_trace_id, _format_span_id
    try:
        from opentelemetry.trace import (
            format_span_id,
            format_trace_id,
            get_current_span,
        )
    except ImportError:  # pragma: no cover - opentelemetry is installed in dev/CI
        _get_current_span = None
        _format_trace_id = None
        _format_span_id = None
        return
    _get_current_span = get_current_span
    _format_trace_id = format_trace_id
    _format_span_id = format_span_id


def _get_correlation_context() -> tuple[str, str]:
    """Extract correlation_id and causation_id from the active domain context.

    Returns a ``(correlation_id, causation_id)`` tuple. The message-based
    extraction from ``g.message_in_context.metadata.domain`` takes precedence.
    When no message is in scope, falls back to the conventional
    ``g.correlation_id`` / ``g.causation_id`` attributes — the documented
    extension point for HTTP middleware, CLI commands, and background jobs
    that want their log records tagged before any domain message exists.
    Both values default to ``""`` when nothing is available.

    Uses the public ``has_domain_context()`` and ``g`` proxy rather than
    reaching into private stack internals.
    """
    try:
        from protean.domain.context import has_domain_context
        from protean.utils.globals import g
    except ImportError:
        return ("", "")

    if not has_domain_context():
        return ("", "")

    # Primary: extract from the active message's domain metadata.
    msg = g.get("message_in_context")
    if msg is not None:
        metadata = getattr(msg, "metadata", None)
        domain_meta = getattr(metadata, "domain", None) if metadata else None
        if domain_meta is not None:
            return (
                domain_meta.correlation_id or "",
                domain_meta.causation_id or "",
            )

    # Fallback: explicit g.correlation_id / g.causation_id — the documented
    # extension point for HTTP middleware, CLI commands, and background jobs
    # that need logs tagged before any domain message exists.
    return (g.get("correlation_id", "") or "", g.get("causation_id", "") or "")


def _get_otel_trace_context() -> tuple[str, str, int]:
    """Extract trace_id, span_id, and trace_flags from the active OTel span.

    Returns a ``(trace_id, span_id, trace_flags)`` tuple. ``trace_id`` is a
    32-character hex string, ``span_id`` is a 16-character hex string, and
    ``trace_flags`` is an integer (``0`` or ``1``).

    Safe no-op when ``opentelemetry`` is not installed (the ``telemetry``
    extra is optional) or when no valid span is active — returns
    ``("", "", 0)``.
    """
    if _get_current_span is _OTEL_UNLOADED:
        _load_otel_helpers()
    if _get_current_span is None:
        return ("", "", 0)

    span = _get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return ("", "", 0)

    return (
        _format_trace_id(ctx.trace_id),
        _format_span_id(ctx.span_id),
        int(ctx.trace_flags),
    )


class ProteanCorrelationFilter(logging.Filter):
    """Stdlib logging filter that adds ``correlation_id`` and ``causation_id``.

    The filter prefers values from ``g.message_in_context.metadata.domain``;
    when no message is in scope it falls back to ``g.correlation_id`` and
    ``g.causation_id``. Outside any domain context both attributes are set
    to ``""`` so formatters that reference ``%(correlation_id)s`` never raise
    ``KeyError``.

    The filter never suppresses records — it always returns ``True``.

    Example::

        import logging
        from protean.integrations.logging import ProteanCorrelationFilter

        logging.getLogger().addFilter(ProteanCorrelationFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        correlation_id, causation_id = _get_correlation_context()
        record.correlation_id = correlation_id  # type: ignore[attr-defined]
        record.causation_id = causation_id  # type: ignore[attr-defined]
        return True


class OTelTraceContextFilter(logging.Filter):
    """Stdlib logging filter that adds OpenTelemetry trace context.

    Reads the current OTel span via ``opentelemetry.trace.get_current_span``
    and sets ``record.trace_id`` (32-char hex), ``record.span_id``
    (16-char hex), and ``record.trace_flags`` (``int``) on the ``LogRecord``.

    When ``opentelemetry`` is not installed or no valid span is active,
    ``trace_id`` and ``span_id`` default to ``""`` and ``trace_flags`` to
    ``0``. The filter never suppresses records — it always returns ``True``.

    Example::

        import logging
        from protean.integrations.logging import OTelTraceContextFilter

        logging.getLogger().addFilter(OTelTraceContextFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        trace_id, span_id, trace_flags = _get_otel_trace_context()
        record.trace_id = trace_id  # type: ignore[attr-defined]
        record.span_id = span_id  # type: ignore[attr-defined]
        record.trace_flags = trace_flags  # type: ignore[attr-defined]
        return True


def protean_correlation_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that injects correlation context into the event dict.

    Reads the active domain context and adds ``correlation_id`` and
    ``causation_id`` keys. Prefers ``g.message_in_context`` metadata, falling
    back to ``g.correlation_id`` / ``g.causation_id`` when no message is in
    scope. Both keys default to ``""`` when no context is available.

    Add this processor to your structlog pipeline::

        import structlog
        from protean.integrations.logging import protean_correlation_processor

        structlog.configure(
            processors=[
                protean_correlation_processor,
                structlog.dev.ConsoleRenderer(),
            ]
        )
    """
    correlation_id, causation_id = _get_correlation_context()
    event_dict["correlation_id"] = correlation_id
    event_dict["causation_id"] = causation_id
    return event_dict


def protean_otel_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that injects OpenTelemetry trace context.

    Reads the active OTel span and adds ``trace_id`` (32-char hex),
    ``span_id`` (16-char hex), and ``trace_flags`` (``int``) to the event
    dict. Safe no-op when ``opentelemetry`` is not installed or no valid
    span is active — fields default to ``""``, ``""``, and ``0``.

    Add this processor to your structlog pipeline::

        import structlog
        from protean.integrations.logging import protean_otel_processor

        structlog.configure(
            processors=[
                protean_otel_processor,
                structlog.dev.ConsoleRenderer(),
            ]
        )
    """
    trace_id, span_id, trace_flags = _get_otel_trace_context()
    event_dict["trace_id"] = trace_id
    event_dict["span_id"] = span_id
    event_dict["trace_flags"] = trace_flags
    return event_dict


# ---------------------------------------------------------------------------
# stdlib LogRecord reserved attribute names
# ---------------------------------------------------------------------------

#: stdlib ``LogRecord`` attribute names that must never be overwritten by
#: user ``extra`` fields or by redaction — they are part of the logging
#: contract (timestamps, source info, levels, etc.). Exposed as a module
#: constant so other subsystems (:mod:`protean.utils.logging`) can share it.
LOG_RECORD_RESERVED_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "process",
        "processName",
        "message",
        "asctime",
        "taskName",
    }
)


# ---------------------------------------------------------------------------
# Sensitive-field redaction
# ---------------------------------------------------------------------------

#: Default keys whose values are replaced with ``[REDACTED]`` in log output.
#: Matching is case-insensitive. Operators can extend this list via
#: ``[logging].redact`` in ``domain.toml``.
DEFAULT_REDACT_KEYS: tuple[str, ...] = (
    "password",
    "token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
    "session",
    "csrf",
)

_REDACTED = "[REDACTED]"

# Hard cap on recursion depth to prevent pathological payloads from triggering
# unbounded traversal. Beyond this depth, nested structures are left untouched
# — redaction is a best-effort hygiene filter, not a security boundary.
_MAX_REDACT_DEPTH = 5


def _build_key_set(redact: Optional[Iterable[str]]) -> frozenset[str]:
    """Return a frozenset of lowercased redact keys."""
    if not redact:
        return frozenset(k.lower() for k in DEFAULT_REDACT_KEYS)
    return frozenset(k.lower() for k in redact)


def _redact(value: Any, keys: frozenset[str], depth: int) -> Any:
    """Return ``value`` with keys in ``keys`` replaced by ``[REDACTED]``.

    Recurses into ``dict`` and ``list`` up to ``_MAX_REDACT_DEPTH`` levels.
    Keys are matched case-insensitively. Other value types are returned
    unchanged. The input is never mutated in place.
    """
    if depth >= _MAX_REDACT_DEPTH:
        return value

    if isinstance(value, dict):
        return {
            k: (
                _REDACTED
                if isinstance(k, str) and k.lower() in keys
                else _redact(v, keys, depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, keys, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, keys, depth + 1) for item in value)
    return value


class ProteanRedactionFilter(logging.Filter):
    """Stdlib logging filter that masks sensitive fields on log records.

    Walks every non-reserved attribute on the ``LogRecord`` and replaces the
    value with ``"[REDACTED]"`` when the attribute name matches one of the
    configured keys (case-insensitive). Nested ``dict`` and ``list`` values
    are scanned up to :data:`_MAX_REDACT_DEPTH` levels deep; deeper nesting
    is left untouched so pathological payloads cannot stall logging.

    The filter never suppresses records — it always returns ``True``.

    Example::

        import logging
        from protean.integrations.logging import ProteanRedactionFilter

        logging.getLogger().addFilter(ProteanRedactionFilter())
    """

    def __init__(self, redact: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self._keys = _build_key_set(redact)

    def filter(self, record: logging.LogRecord) -> bool:
        for attr_name in list(vars(record).keys()):
            if attr_name in LOG_RECORD_RESERVED_ATTRS or attr_name.startswith("_"):
                continue
            if attr_name.lower() in self._keys:
                setattr(record, attr_name, _REDACTED)
                continue
            value = getattr(record, attr_name)
            if isinstance(value, (dict, list, tuple)):
                setattr(record, attr_name, _redact(value, self._keys, 0))
        return True


def make_redaction_processor(
    redact: Optional[Iterable[str]] = None,
) -> Callable[[Any, str, dict[str, Any]], dict[str, Any]]:
    """Build a structlog processor that masks sensitive fields in the event dict.

    Returns a callable suitable for the ``structlog.configure`` ``processors``
    list. The returned processor walks the event dict, replacing values whose
    key matches the configured redact list (case-insensitive) with
    ``"[REDACTED]"``. Nested ``dict`` and ``list`` values are scanned up to
    :data:`_MAX_REDACT_DEPTH` levels deep.

    Example::

        import structlog
        from protean.integrations.logging import make_redaction_processor

        structlog.configure(
            processors=[
                make_redaction_processor(["password", "token"]),
                structlog.processors.JSONRenderer(),
            ]
        )
    """
    keys = _build_key_set(redact)

    def _processor(
        logger: Any, method: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        for k in list(event_dict.keys()):
            if not isinstance(k, str):
                continue
            if k.lower() in keys:
                event_dict[k] = _REDACTED
                continue
            value = event_dict[k]
            if isinstance(value, (dict, list, tuple)):
                event_dict[k] = _redact(value, keys, 0)
        return event_dict

    return _processor


def protean_redaction_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Default-configured redaction processor using :data:`DEFAULT_REDACT_KEYS`.

    Equivalent to ``make_redaction_processor()`` called with no arguments,
    exposed as a module-level callable for direct use in structlog pipelines::

        structlog.configure(
            processors=[
                protean_redaction_processor,
                structlog.processors.JSONRenderer(),
            ]
        )
    """
    return _DEFAULT_REDACTION_PROCESSOR(logger, method, event_dict)


_DEFAULT_REDACTION_PROCESSOR = make_redaction_processor()


# ---------------------------------------------------------------------------
# Security logger helpers
# ---------------------------------------------------------------------------

_security_logger = logging.getLogger("protean.security")

#: Event-type constants emitted on the ``protean.security`` logger. Kept as
#: module constants so call sites never drift typographically from what
#: operators query in log aggregators.
SECURITY_EVENT_INVARIANT_FAILED = "invariant_failed"
SECURITY_EVENT_VALIDATION_FAILED = "validation_failed"
SECURITY_EVENT_INVALID_OPERATION = "invalid_operation"
SECURITY_EVENT_INVALID_STATE = "invalid_state"


def log_security_event(event_type: str, **fields: Any) -> None:
    """Emit a WARNING on the ``protean.security`` logger.

    Dedicated channel for invariant violations, validation failures that
    cross a domain boundary, and other signals operators may want to route
    to a SIEM or alerting pipeline.

    ``correlation_id`` and ``causation_id`` are pulled from the active domain
    context when available, so callers only need to pass domain-specific
    fields (``aggregate``, ``aggregate_id``, ``invariant``, etc.). Keys that
    collide with stdlib ``LogRecord`` attributes are silently dropped to keep
    the logging contract intact.
    """
    correlation_id, causation_id = _get_correlation_context()
    extra = {k: v for k, v in fields.items() if k not in LOG_RECORD_RESERVED_ATTRS}
    extra.setdefault("correlation_id", correlation_id)
    extra.setdefault("causation_id", causation_id)
    _security_logger.warning(event_type, extra=extra)


__all__ = [
    "DEFAULT_REDACT_KEYS",
    "LOG_RECORD_RESERVED_ATTRS",
    "OTelTraceContextFilter",
    "ProteanCorrelationFilter",
    "ProteanRedactionFilter",
    "SECURITY_EVENT_INVALID_OPERATION",
    "SECURITY_EVENT_INVALID_STATE",
    "SECURITY_EVENT_INVARIANT_FAILED",
    "SECURITY_EVENT_VALIDATION_FAILED",
    "log_security_event",
    "make_redaction_processor",
    "protean_correlation_processor",
    "protean_otel_processor",
    "protean_redaction_processor",
]
