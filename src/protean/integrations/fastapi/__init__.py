"""FastAPI integration utilities for Protean."""

try:
    from .exception_handlers import register_exception_handlers
    from .health import create_health_router
    from .middleware import DomainContextMiddleware
    from .telemetry import instrument_app
except ImportError as exc:
    # These submodules import only fastapi (which pulls starlette). fastapi ships
    # in the optional protean[server] extra, so translate a genuinely-absent
    # fastapi into an install hint. Test importability with find_spec, not
    # exc.name: an ImportError from a fastapi that IS installed but broken names
    # "fastapi" too, and we must not tell the user to install what they have.
    from importlib.util import find_spec

    if find_spec("fastapi") is not None:
        raise  # pragma: no cover - a real bug in a present fastapi, surfaced as-is
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
