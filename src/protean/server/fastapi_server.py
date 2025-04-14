"""
FastAPI Server for Protean
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
    """

    def __init__(self, domain_path: str = ".", debug: bool = False) -> None:
        """
        Initialize the FastAPI Server

        Args:
            domain_path (str): Path to the domain module
            debug (bool): Flag to indicate if debug mode is enabled
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
            """Dependency for domain context"""
            with self.domain.domain_context():
                yield

        # Add routes
        @self.app.get("/")
        async def root(domain_ctx=Depends(get_domain_context)):
            """Root endpoint that returns basic information about the domain"""
            return {
                "message": "Protean API Server",
                "domain": self.domain.__class__.__name__,
                "protean_version": importlib.import_module("protean").__version__,
            }

    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """
        Run the FastAPI server using Uvicorn

        Args:
            host (str): Host to bind the server to
            port (int): Port to bind the server to
        """
        import uvicorn

        logger.info(f"Starting Protean FastAPI server at {host}:{port}")
        uvicorn.run(self.app, host=host, port=port)

    def get_app(self) -> FastAPI:
        """
        Get the FastAPI application instance

        Returns:
            FastAPI: The FastAPI application instance
        """
        return self.app
