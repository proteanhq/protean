"""FastAPI integration utilities for Protean."""

try:
    from .exception_handlers import register_exception_handlers
    from .health import create_health_router
    from .middleware import DomainContextMiddleware
    from .telemetry import instrument_app
except ImportError as exc:
    # FastAPI ships in the optional protean[server] extra. Re-raise only the
    # fastapi-missing case with an install hint; any other ImportError points at
    # a real bug in these modules and must surface unchanged.
    if (exc.name or "").split(".")[0] != "fastapi":
        raise  # pragma: no cover - a non-fastapi ImportError is a real bug, surfaced as-is
    from protean.utils.dependencies import missing_dependency_message

    raise ImportError(
        missing_dependency_message(
            "fastapi",
            "server",
            "The FastAPI integration (protean.integrations.fastapi)",
        )
    ) from exc

__all__ = [
    "DomainContextMiddleware",
    "create_health_router",
    "instrument_app",
    "register_exception_handlers",
]
