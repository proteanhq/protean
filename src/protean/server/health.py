"""Lightweight health check HTTP server for the Protean Engine.

Provides Kubernetes-compatible liveness and readiness probes that run
alongside the Engine's event loop.  No external HTTP framework required —
built on ``asyncio.start_server`` with minimal HTTP/1.1 parsing.

Endpoints:
    GET /healthz  — Liveness: engine running, event loop responsive → 200
    GET /livez    — Alias for /healthz
    GET /readyz   — Readiness: providers alive, broker connected,
                    subscriptions active, not shutting down → 200 / 503

Configuration (``domain.toml``):

.. code-block:: toml

    [server.health]
    enabled = true              # default
    host = "127.0.0.1"          # default (loopback); set "0.0.0.0" to expose
    port = 8080                 # default
    port_auto_increment = false # default; try 8081, 8082, ... if 8080 is taken
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from protean.utils.health import (
    STATUS_DEGRADED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    check_brokers,
    check_caches,
    check_event_store,
    check_providers,
)

if TYPE_CHECKING:
    from protean.server.engine import Engine

logger = logging.getLogger(__name__)

# When ``port_auto_increment`` is enabled, how many consecutive ports to try
# starting from the configured one before giving up (8080..8179 by default).
_MAX_PORT_ATTEMPTS = 100


# ---------------------------------------------------------------------------
# Minimal HTTP response builders
# ---------------------------------------------------------------------------

_REASONS = {
    200: "OK",
    404: "Not Found",
    405: "Method Not Allowed",
    503: "Service Unavailable",
}


def _json_response(status_code: int, body: dict[str, Any]) -> bytes:
    """Build a minimal HTTP/1.1 response with JSON body."""
    payload = json.dumps(body).encode("utf-8")
    reason = _REASONS.get(status_code, "Unknown")
    header = (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return header.encode("utf-8") + payload


def _parse_request_line(data: bytes) -> tuple[str, str]:
    """Extract HTTP method and path from the first line of the request."""
    first_line = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
    parts = first_line.split(" ")
    if len(parts) >= 2:
        return parts[0].upper(), parts[1]
    return "", ""


# ---------------------------------------------------------------------------
# Health check logic
# ---------------------------------------------------------------------------


def _check_liveness(engine: Engine) -> dict[str, Any]:
    """Liveness probe: event loop is responsive (proven by this handler executing)."""
    return {
        "status": STATUS_OK,
        "checks": {
            "event_loop": "responsive",
        },
    }


def _check_readiness(engine: Engine) -> dict[str, Any]:
    """Readiness probe: is the engine ready to process messages?

    Checks shutdown state, providers, brokers, event store, caches, and
    subscription count.
    """
    checks: dict[str, Any] = {}
    all_ok = True

    if engine.shutting_down:
        return {
            "status": STATUS_UNAVAILABLE,
            "checks": {"shutting_down": True},
        }
    checks["shutting_down"] = False

    domain = engine.domain

    provider_statuses, providers_ok = check_providers(domain)
    checks["providers"] = provider_statuses
    if not providers_ok:
        all_ok = False

    broker_statuses, brokers_ok = check_brokers(domain)
    checks["brokers"] = broker_statuses
    if not brokers_ok:
        all_ok = False

    es_status, es_ok = check_event_store(domain)
    checks["event_store"] = es_status
    if not es_ok:
        all_ok = False

    cache_statuses, caches_ok = check_caches(domain)
    checks["caches"] = cache_statuses
    if not caches_ok:
        all_ok = False

    total_subscriptions = (
        len(engine._subscriptions)
        + len(engine._broker_subscriptions)
        + len(engine._outbox_processors)
    )
    checks["subscriptions"] = total_subscriptions

    status = STATUS_OK if all_ok else STATUS_DEGRADED
    return {"status": status, "checks": checks}


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class HealthServer:
    """Async HTTP server for Engine health probes.

    Runs as a task on the Engine's event loop.  Start with :meth:`start`
    and stop with :meth:`stop`.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._server: asyncio.AbstractServer | None = None

        try:
            health_config = engine.domain.config.get("server", {}).get("health", {})
        except (AttributeError, TypeError):
            health_config = {}
        self.enabled: bool = health_config.get("enabled", True)
        self.host: str = health_config.get("host", "127.0.0.1")
        self.port: int = health_config.get("port", 8080)
        self.port_auto_increment: bool = health_config.get("port_auto_increment", False)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single HTTP connection."""
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if not data:
                return

            method, path = _parse_request_line(data)

            if method != "GET":
                writer.write(_json_response(405, {"error": "Method Not Allowed"}))
            elif path in ("/healthz", "/livez"):
                result = _check_liveness(self.engine)
                writer.write(_json_response(200, result))
            elif path == "/readyz":
                result = _check_readiness(self.engine)
                code = 200 if result["status"] == STATUS_OK else 503
                writer.write(_json_response(code, result))
            else:
                writer.write(_json_response(404, {"error": "Not Found"}))

            await writer.drain()
        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            logger.debug("Health server connection error", exc_info=True)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        """Start the health check HTTP server.

        Binds ``self.port`` directly unless ``port_auto_increment`` is enabled,
        in which case it walks up to :data:`_MAX_PORT_ATTEMPTS` consecutive
        ports until one is free, updating ``self.port`` to the bound port. This
        lets several engines share a host without colliding on 8080. If no port
        can be bound, the engine logs a warning and continues without probes.
        """
        if not self.enabled:
            logger.debug("Health check server disabled by configuration")
            return

        start_port = self.port
        max_attempts = _MAX_PORT_ATTEMPTS if self.port_auto_increment else 1
        last_error: Exception | None = None

        for candidate in range(start_port, start_port + max_attempts):
            try:
                self._server = await asyncio.start_server(
                    self._handle_connection,
                    host=self.host,
                    port=candidate,
                )
            # OSError: port taken / permission; ValueError/OverflowError: the
            # candidate walked past the valid 0-65535 range. Treat all as
            # "cannot bind here" and keep the engine running without probes.
            except (OSError, ValueError, OverflowError) as e:
                last_error = e
                continue

            # Reflect the port actually bound (candidate, or an OS-assigned one
            # when the configured port is 0).
            self.port = self._server.sockets[0].getsockname()[1]
            logger.info(
                f"Health check server listening on http://{self.host}:{self.port}"
            )
            return

        # For a single attempt this renders as "8080"; for an auto-increment
        # scan, the full "8080-8179" span that was tried.
        attempted = (
            f"{start_port}-{start_port + max_attempts - 1}"
            if self.port_auto_increment
            else str(start_port)
        )
        logger.warning(
            f"Failed to start health check server on {self.host} (port {attempted}): "
            f"{last_error}. Engine will continue without health probes."
        )

    async def stop(self) -> None:
        """Stop the health check HTTP server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Health check server stopped")
