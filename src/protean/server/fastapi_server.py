from __future__ import annotations

import logging
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from protean.domain import Domain
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)


class ProteanFastAPIServer:
    """
    FastAPI server implementation for Protean.

    This class provides a FastAPI server that loads the domain and sets up the necessary
    context for processing requests.
    """

    def __init__(
        self,
        domain: Domain,
        debug: bool = False,
        enable_cors: bool = True,
        cors_origins: list[str] = None,
    ):
        """
        Initialize the FastAPI server.

        Args:
            domain (Domain): The domain to use for the server.
            debug (bool, optional): Flag to indicate if debug mode is enabled. Defaults to False.
            enable_cors (bool, optional): Flag to enable CORS. Defaults to True.
            cors_origins (list[str], optional): List of allowed CORS origins. Defaults to ["*"].
        """
        self.debug = debug
        self.domain = domain
        self.enable_cors = enable_cors
        self.cors_origins = cors_origins or ["*"]

        # Set up logging
        if self.debug:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)

        # Create FastAPI app
        self.app = FastAPI(
            title="Protean",
            description="Protean Server",
            debug=self.debug,
        )

        # Add middleware and routes
        self._setup_middleware()
        self._setup_routes()

        self.domain.init()

    def _setup_middleware(self) -> None:
        """
        Set up middleware for the FastAPI app.
        """
        # Add CORS middleware if enabled
        if self.enable_cors:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=self.cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # Add domain context middleware
        @self.app.middleware("http")
        async def domain_context_middleware(request: Request, call_next):
            """
            Middleware to set up domain context for each request.
            """
            # Enter domain context
            with self.domain.domain_context():
                # Process request
                response = await call_next(request)
            return response

    def _setup_routes(self) -> None:
        """
        Set up routes for the FastAPI app.
        """

        @self.app.get("/", response_class=JSONResponse)
        async def root() -> Dict[str, Any]:
            """
            Root endpoint that returns information about the domain.
            """
            return {
                "status": "success",
                "message": f"Protean API server running with domain: {current_domain.name}",
                "data": {
                    "domain": {
                        "name": current_domain.name,
                        "normalized_name": current_domain.normalized_name,
                    }
                },
            }

    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """
        Run the FastAPI server.

        Args:
            host (str, optional): Host to bind to. Defaults to "0.0.0.0".
            port (int, optional): Port to bind to. Defaults to 8000.
        """
        uvicorn.run(self.app, host=host, port=port)


def create_app(
    domain: Domain,
    debug: bool = False,
    enable_cors: bool = True,
    cors_origins: list[str] = None,
) -> FastAPI:
    """
    Factory function to create a FastAPI app with Protean integration.

    Args:
        domain (Domain): The domain to use for the server.
        debug (bool, optional): Flag to indicate if debug mode is enabled. Defaults to False.
        enable_cors (bool, optional): Flag to enable CORS. Defaults to True.
        cors_origins (list[str], optional): List of allowed CORS origins. Defaults to ["*"].

    Returns:
        FastAPI: The configured FastAPI app.
    """
    server = ProteanFastAPIServer(
        domain=domain,
        debug=debug,
        enable_cors=enable_cors,
        cors_origins=cors_origins,
    )
    return server.app
