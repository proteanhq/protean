"""FastAPI integration utilities for Protean."""

from .exception_handlers import register_exception_handlers
from .health import create_health_router
from .middleware import DomainContextMiddleware
from .telemetry import instrument_app

__all__ = [
    "DomainContextMiddleware",
    "create_health_router",
    "instrument_app",
    "register_exception_handlers",
]
