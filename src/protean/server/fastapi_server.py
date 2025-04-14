"""
FastAPI Server for Protean

This module provides a FastAPI server implementation for Protean domains.
It enables exposing Protean domain models via a RESTful API with automatic
context management and domain loading.

.. versionadded:: 0.12.1
   Added FastAPI server implementation.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class FastAPIServer:
    """
    FastAPI Server implementation for Protean

    This class provides a FastAPI-based server that can expose Protean domains
    via a RESTful API. It automatically loads the domain and sets up a domain
    context before processing each request.

    Features:
    - Automatic domain loading and initialization
    - Domain context management for requests
    - Root endpoint with domain information
    - CORS middleware configuration

    Basic Usage::

        # Start server with CLI command
        $ python -m protean server2 --domain=my_domain

        # Or programmatically
        from protean.server.fastapi_server import FastAPIServer

        server = FastAPIServer(domain_path="my_domain")
        server.run(host="0.0.0.0", port=8000)
    """

    def __init__(self, domain_path: str = ".", debug: bool = False) -> None:
        """
        Initialize the FastAPI Server

        Args:
            domain_path (str): Path to the domain module. Can be a Python module
                path or a file path. Defaults to the current directory.
            debug (bool): Flag to indicate if debug mode is enabled. When
                enabled, more verbose logging will be shown. Defaults to False.

        Raises:
            NoDomainException: If the domain could not be loaded from the
                specified path.
        """
        self.debug = debug
        self.domain_path = domain_path
        self.domain = None
        self.app = FastAPI(
            title="Protean API",
            description="Protean FastAPI Server",
            version="0.1.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )

        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Initialize domain and setup routes
        self._initialize()

    def _initialize(self) -> None:
        """
        Initialize the domain and setup routes

        This method loads the domain from the specified path, initializes it,
        and sets up the API routes. It's called automatically during
        initialization.

        Raises:
            NoDomainException: If the domain could not be loaded from the
                specified path.
        """
        try:
            self.domain = derive_domain(self.domain_path)
        except NoDomainException as exc:
            msg = f"Error loading Protean domain: {exc.args[0]}"
            logger.error(msg)
            raise

        # Initialize the domain
        self.domain.init()

        # Setup the dependency for domain context
        async def get_domain_context():
            """
            Dependency for domain context

            This function is used as a FastAPI dependency to ensure that a
            domain context is set up for each request. The context is
            automatically cleaned up after the request is processed.
            """
            with self.domain.domain_context():
                yield

        # Add routes
        @self.app.get("/")
        async def root(domain_ctx=Depends(get_domain_context)):
            """
            Root endpoint that returns basic information about the domain

            This endpoint provides basic information about the Protean domain
            including the domain name and Protean version.

            Returns:
                dict: A dictionary containing domain information
            """
            return {
                "message": "Protean API Server",
                "domain": self.domain.__class__.__name__,
                "protean_version": importlib.import_module("protean").__version__,
            }

    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """
        Run the FastAPI server using Uvicorn

        This method starts the FastAPI server using Uvicorn as the ASGI server.

        Args:
            host (str): Host to bind the server to. Defaults to "0.0.0.0"
                which binds to all network interfaces.
            port (int): Port to bind the server to. Defaults to 8000.
        """
        import uvicorn

        logger.info(f"Starting Protean FastAPI server at {host}:{port}")
        uvicorn.run(self.app, host=host, port=port)

    def get_app(self) -> FastAPI:
        """
        Get the FastAPI application instance

        This method returns the FastAPI application instance which can be used
        for integration with existing FastAPI applications or ASGI servers.

        Returns:
            FastAPI: The FastAPI application instance
        """
        return self.app
