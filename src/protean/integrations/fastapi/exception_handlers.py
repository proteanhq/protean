"""Standard exception-to-HTTP-response mappings for Protean FastAPI applications.

When a Protean domain context is active (via ``DomainContextMiddleware``), error
responses automatically include ``correlation_id`` in the JSON body so that API
consumers can correlate errors with the originating request without inspecting
response headers.
"""

from typing import Any, Optional, Union

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean.domain.context import has_domain_context
from protean.exceptions import (
    InvalidDataError,
    InvalidOperationError,
    InvalidStateError,
    ObjectNotFoundError,
    ValidationError,
)
from protean.utils.globals import g


def _get_correlation_id() -> Optional[str]:
    """Read the active correlation ID from the domain context, if available.

    Prefers ``g.used_correlation_id`` (set by ``CommandProcessor.enrich()``)
    and falls back to ``g.request_correlation_id`` (set by the middleware).
    Returns ``None`` when no domain context is active.
    """
    if not has_domain_context():
        return None

    return getattr(g, "used_correlation_id", None) or getattr(
        g, "request_correlation_id", None
    )


def _error_body(error: Any, correlation_id: Optional[str]) -> dict[str, Any]:
    """Build the error response body, including ``correlation_id`` when present."""
    body: dict[str, Any] = {"error": error}
    if correlation_id is not None:
        body["correlation_id"] = correlation_id
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers that map Protean exceptions to HTTP responses.

    Call this on any FastAPI app to get standard error handling for Protean
    exceptions.  When a domain context is active, each error response body
    includes a ``correlation_id`` field matching the ``X-Correlation-ID``
    response header.
    """

    @app.exception_handler(ValidationError)
    @app.exception_handler(InvalidDataError)
    async def validation_error_handler(
        request: Request, exc: Union[ValidationError, InvalidDataError]
    ):
        return JSONResponse(
            status_code=400,
            content=_error_body(exc.messages, _get_correlation_id()),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content=_error_body(str(exc), _get_correlation_id()),
        )

    @app.exception_handler(ObjectNotFoundError)
    async def not_found_handler(request: Request, exc: ObjectNotFoundError):
        return JSONResponse(
            status_code=404,
            content=_error_body(str(exc), _get_correlation_id()),
        )

    @app.exception_handler(InvalidStateError)
    async def invalid_state_handler(request: Request, exc: InvalidStateError):
        return JSONResponse(
            status_code=409,
            content=_error_body(str(exc), _get_correlation_id()),
        )

    @app.exception_handler(InvalidOperationError)
    async def invalid_operation_handler(request: Request, exc: InvalidOperationError):
        return JSONResponse(
            status_code=422,
            content=_error_body(str(exc), _get_correlation_id()),
        )
