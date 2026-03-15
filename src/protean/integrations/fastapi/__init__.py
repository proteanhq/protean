"""FastAPI integration utilities for Protean."""

from .exception_handlers import register_exception_handlers
from .middleware import DomainContextMiddleware
from .telemetry import instrument_app

__all__ = [
    "DomainContextMiddleware",
    "instrument_app",
    "register_exception_handlers",
]
