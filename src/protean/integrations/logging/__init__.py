"""Automatic correlation context injection for Python logging.

Provides a stdlib ``logging.Filter`` and a ``structlog`` processor that read
the current domain context (``g.message_in_context``) and inject
``correlation_id`` and ``causation_id`` into every log record — zero
boilerplate required.

Typical usage with stdlib logging::

    import logging
    from protean.integrations.logging import ProteanCorrelationFilter

    handler = logging.StreamHandler()
    handler.addFilter(ProteanCorrelationFilter())
    handler.setFormatter(
        logging.Formatter("%(message)s correlation_id=%(correlation_id)s")
    )
    logging.getLogger().addHandler(handler)

Typical usage with structlog::

    import structlog
    from protean.integrations.logging import protean_correlation_processor

    structlog.configure(
        processors=[
            protean_correlation_processor,
            structlog.dev.ConsoleRenderer(),
        ]
    )

Both integrations are safe to use when no domain context is active — they
silently set fields to empty strings.
"""

import logging
from typing import Any


def _get_correlation_context() -> tuple[str, str]:
    """Extract correlation_id and causation_id from the active domain context.

    Returns a ``(correlation_id, causation_id)`` tuple.  Both values default
    to ``""`` when no domain context or message context is available.
    """
    try:
        from protean.utils.globals import _domain_context_stack
    except ImportError:
        return ("", "")

    top = _domain_context_stack.top
    if top is None:
        return ("", "")

    g = getattr(top, "g", None)
    if g is None:
        return ("", "")

    msg = g.get("message_in_context") if hasattr(g, "get") else None
    if msg is None:
        return ("", "")

    metadata = getattr(msg, "metadata", None) if msg else None
    domain_meta = getattr(metadata, "domain", None) if metadata else None

    if domain_meta is None:
        return ("", "")

    return (
        domain_meta.correlation_id or "",
        domain_meta.causation_id or "",
    )


class ProteanCorrelationFilter(logging.Filter):
    """Stdlib logging filter that adds ``correlation_id`` and ``causation_id``.

    When a Protean domain context is active and ``g.message_in_context``
    holds a message with metadata, the filter sets the corresponding
    attributes on the ``LogRecord``.  Otherwise both attributes are set to
    ``""`` so formatters that reference ``%(correlation_id)s`` never raise
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


def protean_correlation_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that injects correlation context into the event dict.

    Reads ``g.message_in_context`` from the active Protean domain context and
    adds ``correlation_id`` and ``causation_id`` keys.  When no context is
    available, the keys are set to ``""``.

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


__all__ = [
    "ProteanCorrelationFilter",
    "protean_correlation_processor",
]
