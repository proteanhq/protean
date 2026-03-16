"""OpenTelemetry auto-instrumentation for FastAPI applications.

Wraps ``opentelemetry-instrumentation-fastapi`` with Protean's domain-scoped
tracer and meter providers.  When telemetry is enabled on a domain, HTTP
request spans automatically parent command/event processing spans via
standard OTEL context propagation.

Usage::

    from protean.integrations.fastapi import instrument_app

    instrument_app(app, domain)

The call is safe even when ``opentelemetry`` is not installed — it returns
``False`` and logs a warning.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from protean.domain import Domain

logger = logging.getLogger(__name__)


def instrument_app(
    app: FastAPI,
    domain: Domain,
    *,
    excluded_urls: str | None = None,
    **kwargs: Any,
) -> bool:
    """Auto-instrument a FastAPI app with OpenTelemetry using domain-scoped providers.

    Applies ``FastAPIInstrumentor.instrument_app()`` so that every HTTP request
    creates an OTEL span with standard semantic conventions (``http.method``,
    ``http.route``, ``http.status_code``).  These HTTP spans automatically
    become parents of any ``protean.command.process`` or
    ``protean.handler.execute`` spans created during the request, thanks to
    OTEL context propagation.

    Args:
        app: The FastAPI application instance.
        domain: The Protean domain whose tracer/meter providers are used.
        excluded_urls: Comma-separated URL patterns to exclude from tracing
            (e.g. ``"health,ready"``).
        **kwargs: Additional keyword arguments forwarded to
            ``FastAPIInstrumentor.instrument_app()``.

    Returns:
        ``True`` if instrumentation was applied, ``False`` otherwise
        (telemetry disabled, packages missing, or already instrumented).
    """
    config = domain.config.get("telemetry", {})
    if not config.get("enabled", False):
        return False

    # Check early to avoid side-effects when already instrumented
    if getattr(app, "_is_instrumented_by_opentelemetry", False):
        logger.debug(
            "FastAPI app is already instrumented with OpenTelemetry, skipping."
        )
        return False

    from protean.utils.telemetry import (
        get_meter_provider,
        get_tracer_provider,
        init_telemetry,
        instrument_fastapi_app,
    )

    # Ensure domain telemetry providers are initialized
    if not getattr(domain, "_otel_init_attempted", False):
        init_telemetry(domain)

    instrument_kwargs: dict[str, Any] = {}
    tracer_provider = get_tracer_provider(domain)
    if tracer_provider is not None:
        instrument_kwargs["tracer_provider"] = tracer_provider
    meter_provider = get_meter_provider(domain)
    if meter_provider is not None:
        instrument_kwargs["meter_provider"] = meter_provider
    if excluded_urls is not None:
        instrument_kwargs["excluded_urls"] = excluded_urls
    instrument_kwargs.update(kwargs)

    if not instrument_fastapi_app(app, **instrument_kwargs):
        return False

    logger.info(
        "FastAPI app instrumented with OpenTelemetry for domain '%s'",
        domain.name,
    )
    return True
