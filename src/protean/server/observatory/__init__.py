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
import logging
from pathlib import Path
from typing import List

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from protean.domain import Domain

from .api import create_api_router
from .metrics import create_metrics_endpoint
from .sse import create_sse_endpoint

logger = logging.getLogger(__name__)

_DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


class _GracefulShutdownMiddleware:
    """ASGI middleware that absorbs CancelledError during server shutdown.

    When uvicorn force-cancels tasks on shutdown, long-lived SSE connections
    get a CancelledError that Starlette propagates as an unhandled exception,
    producing an ugly traceback. This middleware catches it at the ASGI layer
    so the shutdown is clean.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message):
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
    - GET /            — Embedded HTML dashboard
    - GET /stream      — SSE real-time trace events
    - GET /api/health  — Infrastructure health
    - GET /api/outbox  — Outbox status per domain
    - GET /api/streams — Redis stream info
    - GET /api/stats   — Throughput/error rate stats
    - GET /metrics     — Prometheus text exposition
    """

    def __init__(
        self,
        domains: List[Domain],
        title: str = "Protean Observatory",
        enable_cors: bool = True,
        cors_origins: list[str] = None,
    ) -> None:
        self.domains = domains
        self.title = title
        self.enable_cors = enable_cors
        self.cors_origins = cors_origins or ["*"]

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
        # Dashboard (root)
        @self.app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def dashboard():
            if _DASHBOARD_HTML_PATH.exists():
                return HTMLResponse(content=_DASHBOARD_HTML_PATH.read_text())
            return HTMLResponse(
                content="<h1>Protean Observatory</h1><p>Dashboard HTML not found.</p>",
                status_code=500,
            )

        # REST API endpoints
        api_router = create_api_router(self.domains)
        self.app.include_router(api_router, prefix="/api")

        # SSE streaming endpoint
        sse_endpoint = create_sse_endpoint(self.domains)
        self.app.add_api_route("/stream", sse_endpoint, methods=["GET"])

        # Prometheus metrics endpoint
        metrics_endpoint = create_metrics_endpoint(self.domains)
        self.app.add_api_route("/metrics", metrics_endpoint, methods=["GET"])

    def run(self, host: str = "0.0.0.0", port: int = 9000) -> None:
        """Run the observatory server."""
        logger.info(f"Starting Protean Observatory on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port)


def create_observatory_app(
    domains: List[Domain],
    title: str = "Protean Observatory",
) -> FastAPI:
    """Factory function to create an Observatory FastAPI app for uvicorn."""
    observatory = Observatory(domains=domains, title=title)
    return observatory.app
