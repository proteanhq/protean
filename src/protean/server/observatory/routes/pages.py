"""Page routes for the Observatory — Jinja2-rendered views.

Each view gets a dedicated route that renders its template with
initial context data. JavaScript handles live updates via SSE and polling.
"""

import logging
from typing import List

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from protean.domain import Domain

logger = logging.getLogger(__name__)


def _get_domain_names(domains: List[Domain]) -> list[str]:
    """Extract domain names for template context."""
    return [d.name for d in domains]


def create_page_router(
    domains: List[Domain],
    templates: Jinja2Templates,
) -> APIRouter:
    """Create the page router with all view routes."""
    router = APIRouter()
    domain_names = _get_domain_names(domains)

    def _ctx(active_page: str, **extra) -> dict:
        """Build the base template context (without request)."""
        return {
            "domains": domain_names,
            "active_page": active_page,
            **extra,
        }

    @router.get("/")
    async def overview(request: Request):
        """Overview — Landing page. Answers 'is everything okay?' at a glance."""
        return templates.TemplateResponse(request, "overview.html", _ctx("overview"))

    @router.get("/handlers")
    async def handlers(request: Request):
        """Handlers — Detailed operational view of every message handler."""
        return templates.TemplateResponse(request, "handlers.html", _ctx("handlers"))

    @router.get("/flows")
    async def flows(request: Request):
        """Event Flows — Visualize runtime message flow through the system."""
        return templates.TemplateResponse(request, "flows.html", _ctx("flows"))

    @router.get("/processes")
    async def processes(request: Request):
        """Processes — Monitor long-running process managers and sagas."""
        return templates.TemplateResponse(request, "processes.html", _ctx("processes"))

    @router.get("/eventstore")
    async def eventstore(request: Request):
        """Event Store — Monitor event store health and stream statistics."""
        return templates.TemplateResponse(
            request, "eventstore.html", _ctx("eventstore")
        )

    @router.get("/infrastructure")
    async def infrastructure(request: Request):
        """Infrastructure — Monitor infrastructure dependencies."""
        return templates.TemplateResponse(
            request, "infrastructure.html", _ctx("infrastructure")
        )

    return router
