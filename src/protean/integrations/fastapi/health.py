"""FastAPI health check router factory for Protean applications.

Provides standardised ``/healthz`` and ``/readyz`` endpoints that inspect
the domain's infrastructure (database providers, brokers, event store,
caches) and return structured JSON responses.

Usage::

    from fastapi import FastAPI
    from protean.integrations.fastapi.health import create_health_router

    app = FastAPI()
    app.include_router(create_health_router(domain))
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from protean.utils.health import (
    STATUS_DEGRADED,
    STATUS_OK,
    check_brokers,
    check_caches,
    check_event_store,
    check_providers,
)

if TYPE_CHECKING:
    from protean.domain import Domain


def create_health_router(
    domain: Domain,
    *,
    prefix: str = "",
    tags: list[str] | None = None,
) -> APIRouter:
    """Create a FastAPI router with health check endpoints.

    Args:
        domain: An initialised Protean domain.
        prefix: URL prefix for the health endpoints (default: no prefix).
        tags: OpenAPI tags for the endpoints.

    Returns:
        A :class:`fastapi.APIRouter` with ``/healthz``, ``/livez``, and
        ``/readyz`` routes.

    Example::

        app = FastAPI()
        app.include_router(create_health_router(domain))

        # Or with a prefix:
        app.include_router(create_health_router(domain, prefix="/api"))
    """
    router = APIRouter(prefix=prefix, tags=tags or ["health"])

    @router.get("/healthz")
    @router.get("/livez")
    async def liveness() -> JSONResponse:
        """Liveness probe: is the application process alive?"""
        return JSONResponse(
            status_code=200,
            content={
                "status": STATUS_OK,
                "checks": {"application": "running"},
            },
        )

    @router.get("/readyz")
    async def readiness() -> JSONResponse:
        """Readiness probe: are all infrastructure dependencies reachable?"""
        checks: dict[str, Any] = {}
        all_ok = True

        with domain.domain_context():
            provider_statuses, providers_ok = check_providers(domain)
            checks["providers"] = provider_statuses
            if not providers_ok:
                all_ok = False

            broker_statuses, brokers_ok = check_brokers(domain)
            checks["brokers"] = broker_statuses
            if not brokers_ok:
                all_ok = False

            es_status, es_ok = check_event_store(domain)
            checks["event_store"] = es_status
            if not es_ok:
                all_ok = False

            cache_statuses, caches_ok = check_caches(domain)
            checks["caches"] = cache_statuses
            if not caches_ok:
                all_ok = False

        status = STATUS_OK if all_ok else STATUS_DEGRADED
        code = 200 if all_ok else 503

        return JSONResponse(
            status_code=code,
            content={"status": status, "checks": checks},
        )

    return router
