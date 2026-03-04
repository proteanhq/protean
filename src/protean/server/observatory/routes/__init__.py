"""Observatory route modules.

Composes page routes (Jinja2-rendered views) and additional API routes
into FastAPI routers that the Observatory class mounts.
"""

from typing import List

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

from protean.domain import Domain

from .flows import create_flows_router
from .handlers import create_handlers_router
from .pages import create_page_router
from .processes import create_processes_router


def create_all_routes(
    domains: List[Domain],
    templates: Jinja2Templates,
) -> tuple[APIRouter, APIRouter]:
    """Create all Observatory routes.

    Returns:
        Tuple of (page_router, api_router).
        page_router: Jinja2-rendered page views.
        api_router: Additional JSON API endpoints.
    """
    page_router = create_page_router(domains, templates)

    api_router = APIRouter()
    api_router.include_router(create_handlers_router(domains))
    api_router.include_router(create_flows_router(domains))
    api_router.include_router(create_processes_router(domains))

    return page_router, api_router
