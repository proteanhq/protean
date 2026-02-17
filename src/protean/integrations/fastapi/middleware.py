"""Domain context middleware for FastAPI applications.

Automatically pushes the correct Protean domain context per HTTP request
based on URL path prefix matching. Essential for multi-domain applications
where different URL paths map to different bounded contexts.

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

from typing import Callable, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from protean.domain import Domain


class DomainContextMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that activates the correct Protean domain context per request.

    Maps URL path prefixes to Domain instances. For each incoming request, finds
    the longest matching prefix and pushes that domain's context for the duration
    of the request lifecycle. Requests that don't match any prefix pass through
    without a domain context (suitable for health checks, docs, static assets).

    Args:
        app: The ASGI application (injected by Starlette).
        route_domain_map: Dict mapping URL path prefixes to Domain instances.
            Sorted by prefix length descending for longest-prefix-first matching.
        resolver: Optional custom callable that maps a URL path to a Domain
            (or None). When provided, ``route_domain_map`` is ignored.
    """

    def __init__(
        self,
        app: ASGIApp,
        route_domain_map: Optional[dict[str, Domain]] = None,
        resolver: Optional[Callable[[str], Optional[Domain]]] = None,
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

    def _resolve_domain(self, path: str) -> Optional[Domain]:
        """Resolve a URL path to a Domain instance."""
        if self._resolver:
            return self._resolver(path)

        for prefix, domain in self._route_domain_map.items():
            if path.startswith(prefix):
                return domain

        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        """Push domain context for the request and forward to the next handler."""
        domain = self._resolve_domain(request.url.path)

        if domain is not None:
            with domain.domain_context():
                return await call_next(request)

        return await call_next(request)
