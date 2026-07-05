"""Protean Observatory — Framework-level message observability server.

A dedicated FastAPI server for real-time monitoring of the Protean event pipeline.
Runs on its own port (default 9000), separate from the application API server.

Usage:
    # Single domain
    observatory = Observatory(domains=[domain])
    observatory.run(port=9000)

    # Multi-domain (e.g., ShopStream)
    observatory = Observatory(domains=[identity, catalogue])
    observatory.run(port=9000)

    # Factory for uvicorn
    app = create_observatory_app(domains=[identity, catalogue])
"""

import asyncio
import ipaddress
import logging
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from protean.domain import Domain

from .api import create_api_router
from .metrics import create_metrics_endpoint
from .routes import create_all_routes
from .sse import create_sse_endpoint

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


class _GracefulShutdownMiddleware:
    """ASGI middleware that absorbs CancelledError during server shutdown.

    When uvicorn force-cancels tasks on shutdown, long-lived SSE connections
    get a CancelledError that Starlette propagates as an unhandled exception,
    producing an ugly traceback. This middleware catches it at the ASGI layer
    so the shutdown is clean.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            # Expected during shutdown for SSE connections.
            # If the response was already streaming (headers sent), send
            # the final empty body so uvicorn doesn't log
            # "ASGI callable returned without completing response."
            if response_started:
                try:
                    await send(
                        {"type": "http.response.body", "body": b"", "more_body": False}
                    )
                except Exception:
                    pass


class Observatory:
    """Dedicated observability server for Protean applications.

    Provides:
    - GET /                    — Overview dashboard (Jinja2-rendered)
    - GET /handlers            — Handler monitoring view
    - GET /processes           — Process manager monitoring
    - GET /eventstore          — Event store health
    - GET /infrastructure      — Infrastructure status
    - GET /stream              — SSE real-time trace events
    - GET /api/*               — REST API endpoints
    - GET /metrics             — Prometheus text exposition
    - GET /static/*            — Vendored CSS/JS assets
    """

    def __init__(
        self,
        domains: List[Domain],
        title: str = "Protean Observatory",
        enable_cors: bool = True,
        cors_origins: Optional[list[str]] = None,
    ) -> None:
        self.domains = domains
        self.title = title
        self.enable_cors = enable_cors
        self.cors_origins = cors_origins or ["*"]

        # Jinja2 templates
        self.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

        # Create FastAPI app
        self.app = FastAPI(
            title=self.title,
            description="Real-time message flow observability for Protean applications",
            docs_url=None,
            redoc_url=None,
        )

        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self) -> None:
        if self.enable_cors:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=self.cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # Must be the outermost middleware (added last = runs first)
        # so it wraps everything including Starlette's StreamingResponse
        self.app.add_middleware(_GracefulShutdownMiddleware)

    def _setup_routes(self) -> None:
        # Static files (vendored CSS/JS assets)
        self.app.mount(
            "/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="static",
        )

        # Page routes (Jinja2-rendered views)
        page_router, new_api_router = create_all_routes(self.domains, self.templates)
        self.app.include_router(page_router)

        # REST API endpoints (existing + new)
        api_router = create_api_router(self.domains)
        self.app.include_router(api_router, prefix="/api")
        self.app.include_router(new_api_router, prefix="/api")

        # SSE streaming endpoint
        sse_endpoint = create_sse_endpoint(self.domains)
        self.app.add_api_route("/stream", sse_endpoint, methods=["GET"])

        # Prometheus metrics endpoint
        metrics_endpoint = create_metrics_endpoint(self.domains)
        self.app.add_api_route("/metrics", metrics_endpoint, methods=["GET"])

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        """Whether ``host`` keeps the server reachable only from this machine.

        Uses a semantic check so every loopback form is recognized (the whole
        ``127.0.0.0/8`` range, ``::1`` in any spelling), plus the literal
        ``localhost``. Anything that cannot be proven loopback (other hostnames,
        ``0.0.0.0``, ``::``) is treated as exposed.
        """
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def run(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        """Run the observatory server.

        Defaults to binding loopback only. The Observatory is unauthenticated
        and exposes domain internals and DLQ management endpoints, so binding it
        to a non-loopback address emits a warning.
        """
        if not self._is_loopback_host(host):
            logger.warning(
                "Observatory is binding to %s, reachable beyond this host. It "
                "has no authentication and exposes domain internals and DLQ "
                "management endpoints. Restrict it to a trusted network behind "
                "an authenticating reverse proxy.",
                host,
            )
        logger.info(f"Starting Protean Observatory on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port)


def create_observatory_app(
    domains: List[Domain],
    title: str = "Protean Observatory",
) -> FastAPI:
    """Factory function to create an Observatory FastAPI app for uvicorn."""
    observatory = Observatory(domains=domains, title=title)
    return observatory.app
