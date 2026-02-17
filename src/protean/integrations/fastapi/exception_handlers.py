"""Standard exception-to-HTTP-response mappings for Protean FastAPI applications."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean.exceptions import (
    InvalidDataError,
    InvalidOperationError,
    InvalidStateError,
    ObjectNotFoundError,
    ValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers that map Protean exceptions to HTTP responses.

    Call this on any FastAPI app to get standard error handling for Protean
    exceptions.
    """

    @app.exception_handler(ValidationError)
    @app.exception_handler(InvalidDataError)
    async def validation_error_handler(request: Request, exc):
        return JSONResponse(status_code=400, content={"error": exc.messages})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(ObjectNotFoundError)
    async def not_found_handler(request: Request, exc: ObjectNotFoundError):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(InvalidStateError)
    async def invalid_state_handler(request: Request, exc: InvalidStateError):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(InvalidOperationError)
    async def invalid_operation_handler(request: Request, exc: InvalidOperationError):
        return JSONResponse(status_code=422, content={"error": str(exc)})
