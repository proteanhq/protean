"""Domain context middleware for FastAPI applications.

Automatically pushes the correct Protean domain context per HTTP request
based on URL path prefix matching. Essential for multi-domain applications
where different URL paths map to different bounded contexts.

Also emits one wide event per HTTP request on the ``protean.access.http``
logger, capturing the request envelope (method, path, status, duration),
the request/correlation IDs, and the domain commands dispatched during
the request.

Usage::

    from protean.integrations.fastapi import DomainContextMiddleware

    app.add_middleware(
        DomainContextMiddleware,
        route_domain_map={
            "/customers": identity_domain,
            "/products": catalogue_domain,
        },
    )
"""

from __future__ import annotations

import logging
import time
from contextlib import nullcontext
from typing import Any, Callable, Iterable, Optional
from uuid import uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from protean.domain import Domain
from protean.integrations.logging import LOG_RECORD_RESERVED_ATTRS
from protean.utils.globals import g
from protean.utils.logging import http_access_logger

_CORRELATION_HEADER = "X-Correlation-ID"
_REQUEST_ID_HEADER = "X-Request-ID"
_FORWARDED_FOR_HEADER = "x-forwarded-for"
_USER_AGENT_HEADER = "user-agent"

# Cap overly-large User-Agent strings so operators cannot accidentally blow
# up log storage with a crafted header. Matches the issue spec (256 chars).
_USER_AGENT_MAX_CHARS = 256

# Keys that the middleware fills in itself. Application-provided context
# bound via ``bind_event_context`` must not silently overwrite them.
_HTTP_FRAMEWORK_FIELDS = frozenset(
    {
        "http_method",
        "http_path",
        "http_status",
        "http_duration_ms",
        "route_name",
        "route_pattern",
        "request_id",
        "correlation_id",
        "commands_dispatched",
        "commands_dispatched_count",
        "client_ip",
        "user_agent",
        "http_request_headers",
        "http_response_headers",
        "error_type",
        "error_message",
    }
)


class DomainContextMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that activates the correct Protean domain context per request.

    Maps URL path prefixes to Domain instances. For each incoming request, finds
    the longest matching prefix and pushes that domain's context for the duration
    of the request lifecycle. Requests that don't match any prefix pass through
    without a domain context (suitable for health checks, docs, static assets).

    Automatically extracts ``X-Correlation-ID`` (falling back to ``X-Request-ID``)
    from incoming request headers and stores the value in ``g.request_correlation_id``
    so that :meth:`CommandProcessor.enrich` can use it as the default correlation ID.
    The response always includes an ``X-Correlation-ID`` header reflecting the ID
    that was used.

    In addition, the middleware emits one wide event per HTTP request on the
    ``protean.access.http`` logger (INFO for 2xx/3xx, WARNING for 4xx, ERROR
    for 5xx). The event carries the request envelope, the commands dispatched
    during the request, and the correlation IDs so operators can link HTTP
    activity with the domain-layer ``protean.access`` wide events produced by
    :func:`protean.utils.logging.access_log_handler`.

    Args:
        app: The ASGI application (injected by Starlette).
        route_domain_map: Dict mapping URL path prefixes to Domain instances.
            Sorted by prefix length descending for longest-prefix-first matching.
        resolver: Optional custom callable that maps a URL path to a Domain
            (or None). When provided, ``route_domain_map`` is ignored.
        emit_http_wide_event: When ``True`` (default), emit one wide event per
            HTTP request on ``protean.access.http``. When ``False``, suppress
            wide events entirely. When ``None`` (default), defer to the
            ``[logging.http].enabled`` flag on the resolved domain's config.
        exclude_paths: Iterable of exact request paths to exclude from wide
            event emission (e.g. ``["/healthz", "/readyz"]``). When ``None``
            (default), defer to ``[logging.http].exclude_paths``.
        log_request_headers: When ``True``, include the request headers dict
            in the wide event (redacted by the framework's redaction filter).
            When ``None`` (default), defer to ``[logging.http].log_request_headers``.
        log_response_headers: When ``True``, include the response headers dict
            in the wide event. When ``None`` (default), defer to
            ``[logging.http].log_response_headers``.
    """

    def __init__(
        self,
        app: ASGIApp,
        route_domain_map: Optional[dict[str, Domain]] = None,
        resolver: Optional[Callable[[str], Optional[Domain]]] = None,
        emit_http_wide_event: Optional[bool] = None,
        exclude_paths: Optional[Iterable[str]] = None,
        log_request_headers: Optional[bool] = None,
        log_response_headers: Optional[bool] = None,
    ) -> None:
        super().__init__(app)

        if resolver is None and not route_domain_map:
            raise ValueError(
                "DomainContextMiddleware requires either route_domain_map or resolver"
            )

        # Sort by prefix length descending for longest-prefix-first matching
        self._route_domain_map = (
            dict(
                sorted(route_domain_map.items(), key=lambda x: len(x[0]), reverse=True)
            )
            if route_domain_map
            else {}
        )
        self._resolver = resolver

        # Explicit middleware overrides win over per-domain [logging.http]
        # config values; a ``None`` override defers to the domain config.
        self._emit_http_wide_event_override = emit_http_wide_event
        self._exclude_paths_override = (
            frozenset(exclude_paths) if exclude_paths is not None else None
        )
        self._log_request_headers_override = log_request_headers
        self._log_response_headers_override = log_response_headers

        # Pick a "fallback" domain for sourcing [logging.http] config when no
        # request-specific domain is resolvable (unmapped paths, resolver-only
        # setups). The first registered domain is a stable choice — most
        # FastAPI apps only use one domain.
        self._default_domain: Optional[Domain] = next(
            iter(self._route_domain_map.values()), None
        )

    def _resolve_domain(self, path: str) -> Optional[Domain]:
        """Resolve a URL path to a Domain instance."""
        if self._resolver:
            return self._resolver(path)

        for prefix, domain in self._route_domain_map.items():
            if path.startswith(prefix):
                return domain

        return None

    @staticmethod
    def _extract_correlation_id(request: Request) -> Optional[str]:
        """Extract correlation ID from request headers.

        Checks ``X-Correlation-ID`` first, then falls back to ``X-Request-ID``.
        Returns ``None`` when neither header is present.
        """
        return request.headers.get(_CORRELATION_HEADER) or request.headers.get(
            _REQUEST_ID_HEADER
        )

    def _resolve_http_logging_config(
        self, request_domain: Optional[Domain]
    ) -> dict[str, Any]:
        """Build the effective HTTP logging config for this request.

        Explicit middleware constructor overrides win; otherwise the
        resolved domain's ``[logging.http]`` section is used, falling back
        to the middleware's default domain, and finally built-in defaults.
        """
        domain = request_domain or self._default_domain
        domain_cfg: dict[str, Any] = (
            (domain.config.get("logging", {}) or {}).get("http", {}) or {}
            if domain is not None
            else {}
        )

        def _pick(override: Any, key: str, default: Any) -> Any:
            return override if override is not None else domain_cfg.get(key, default)

        exclude_paths = _pick(self._exclude_paths_override, "exclude_paths", [])
        if not isinstance(exclude_paths, frozenset):
            exclude_paths = frozenset(exclude_paths)

        return {
            "enabled": bool(
                _pick(self._emit_http_wide_event_override, "enabled", True)
            ),
            "exclude_paths": exclude_paths,
            "log_request_headers": bool(
                _pick(self._log_request_headers_override, "log_request_headers", False)
            ),
            "log_response_headers": bool(
                _pick(
                    self._log_response_headers_override, "log_response_headers", False
                )
            ),
        }

    async def dispatch(self, request: Request, call_next) -> Response:
        """Push domain context for the request and forward to the next handler."""
        domain = self._resolve_domain(request.url.path)
        correlation_id = self._extract_correlation_id(request)
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid4().hex

        http_config = self._resolve_http_logging_config(domain)
        emit_wide_event = http_config["enabled"] and (
            request.url.path not in http_config["exclude_paths"]
        )

        started_at = time.perf_counter()
        commands_dispatched: list[str] = []
        # ``http_extras`` is mutated by reference through ``g`` so that
        # ``bind_event_context`` calls made inside the endpoint are visible
        # back here. Starlette runs ``call_next`` in a child asyncio task
        # whose ``contextvars`` copy is not observable from the parent, so
        # structlog bindings alone would be lost at the HTTP boundary.
        http_extras: dict[str, Any] = {}

        ctx = domain.domain_context() if domain is not None else nullcontext()
        with ctx:
            if domain is not None:
                if correlation_id is None:
                    correlation_id = uuid4().hex
                g.request_correlation_id = correlation_id
                # ``ProteanCorrelationFilter`` reads ``g.correlation_id`` to
                # tag log records with the same correlation_id that domain
                # wide events inherit from message metadata.
                g.correlation_id = correlation_id
                g._http_commands_dispatched = commands_dispatched
                g._http_wide_event_extras = http_extras

            response, status_code, error_info = await self._run_endpoint(
                request, call_next
            )

            if response is not None:
                response.headers[_REQUEST_ID_HEADER] = request_id
                if domain is not None:
                    # Prefer the correlation id command processing actually
                    # used (set by CommandProcessor.enrich), falling back to
                    # the request-supplied one when no command ran.
                    # ``correlation_id`` is guaranteed non-None in this branch
                    # because the block above auto-generates one when absent.
                    assert correlation_id is not None
                    used_id: str = (
                        getattr(g, "used_correlation_id", None) or correlation_id
                    )
                    response.headers[_CORRELATION_HEADER] = used_id

        if emit_wide_event:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            # Merge structlog contextvars (parent-task bindings) with the
            # extras dict shared through ``g`` (child-task bindings from
            # ``bind_event_context``). Child-task writes win on conflict.
            app_context = {
                **structlog.contextvars.get_contextvars(),
                **http_extras,
            }
            self._emit_http_wide_event(
                request=request,
                response=response,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                correlation_id=correlation_id,
                commands_dispatched=commands_dispatched,
                error_info=error_info,
                app_context=app_context,
                config=http_config,
            )

        if error_info is not None:
            raise error_info
        return response  # type: ignore[return-value]

    @staticmethod
    async def _run_endpoint(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> tuple[Optional[Response], int, Optional[Exception]]:
        """Run the downstream handler and normalise the result.

        Returns a ``(response, status_code, error)`` tuple. When the
        downstream raises, ``response`` is ``None``, ``status_code`` is
        ``500``, and ``error`` carries the exception for later re-raising
        after the wide event has been emitted. ``Exception`` is caught (not
        ``BaseException``) so ``SystemExit`` and ``KeyboardInterrupt`` still
        propagate immediately as intended.
        """
        try:
            response = await call_next(request)
        except Exception as exc:
            return None, 500, exc
        return response, response.status_code, None

    @staticmethod
    def _emit_http_wide_event(
        *,
        request: Request,
        response: Optional[Response],
        status_code: int,
        duration_ms: float,
        request_id: str,
        correlation_id: Optional[str],
        commands_dispatched: list[str],
        error_info: Optional[Exception],
        app_context: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Build and log the HTTP wide event.

        Never raises — emission failures fall back to a DEBUG log on the
        internal logger so broken observability cannot crash an otherwise
        successful request.
        """
        try:
            route = request.scope.get("route")
            route_name = getattr(route, "name", "") or ""
            route_pattern = getattr(route, "path", "") or ""

            # Prefer X-Forwarded-For (first hop) to capture the original
            # client when a reverse proxy is in front, falling back to the
            # direct peer recorded by Starlette.
            client_ip = ""
            forwarded = request.headers.get(_FORWARDED_FOR_HEADER)
            if forwarded:
                client_ip = forwarded.split(",", 1)[0].strip()
            elif request.client is not None:
                client_ip = request.client.host or ""

            user_agent = (request.headers.get(_USER_AGENT_HEADER) or "")[
                :_USER_AGENT_MAX_CHARS
            ]

            # Start from app-provided context so ``bind_event_context``
            # fields land on the wide event — but strip any keys that
            # collide with framework-reserved names or stdlib LogRecord
            # attributes, to avoid silent overwrites and KeyError on the
            # logging side.
            forbidden = _HTTP_FRAMEWORK_FIELDS | LOG_RECORD_RESERVED_ATTRS
            extra: dict[str, Any] = {
                k: v for k, v in app_context.items() if k not in forbidden
            }
            extra.update(
                {
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": status_code,
                    "http_duration_ms": duration_ms,
                    "route_name": route_name,
                    "route_pattern": route_pattern,
                    "request_id": request_id,
                    "correlation_id": correlation_id or "",
                    "commands_dispatched": list(commands_dispatched),
                    "commands_dispatched_count": len(commands_dispatched),
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                }
            )

            if config["log_request_headers"]:
                extra["http_request_headers"] = dict(request.headers)
            if config["log_response_headers"] and response is not None:
                extra["http_response_headers"] = dict(response.headers)

            if error_info is not None:
                extra["error_type"] = type(error_info).__name__
                extra["error_message"] = str(error_info)[:256]
                http_access_logger.error(
                    "access.http_failed",
                    extra=extra,
                    exc_info=(type(error_info), error_info, error_info.__traceback__),
                )
            elif status_code >= 500:
                http_access_logger.error("access.http_failed", extra=extra)
            elif status_code >= 400:
                http_access_logger.warning("access.http_completed", extra=extra)
            else:
                http_access_logger.info("access.http_completed", extra=extra)
        except Exception:
            logging.getLogger(__name__).debug(
                "http_wide_event_emission_failed", exc_info=True
            )
