"""Infrastructure monitoring API for the Protean Observatory.

Provides connection health status for all infrastructure adapters
(database, broker, event store, cache) and server information.

Endpoints:
    GET /infrastructure/status  — Full infrastructure status
"""

from __future__ import annotations

import logging
import platform
import re
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import protean

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Pattern to detect URIs with credentials
_URI_PATTERN = re.compile(
    r"((?:redis|postgresql|postgres|mysql|sqlite|mongodb|amqp|http|https)"
    r"://)"  # scheme
    r"([^@]+@)?"  # optional user:pass@
    r"(.+)",  # host + path
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def sanitize_config(config: Any) -> Any:
    """Strip sensitive values (URIs, passwords) from config for display.

    - URIs have credentials masked (``user:pass@host`` → ``***@host``)
    - Keys containing 'password', 'secret', 'token' are replaced with '***'
    """
    if isinstance(config, dict):
        sanitized: dict[str, Any] = {}
        for key, value in config.items():
            lower_key = str(key).lower()
            if any(s in lower_key for s in ("password", "secret", "token", "api_key")):
                sanitized[key] = "***"
            else:
                sanitized[key] = sanitize_config(value)
        return sanitized
    elif isinstance(config, str):
        match = _URI_PATTERN.match(config)
        if match:
            scheme, _creds, host_path = match.groups()
            return f"{scheme}***@{host_path}" if _creds else config
        return config
    elif isinstance(config, (list, tuple)):
        return [sanitize_config(item) for item in config]
    else:
        return config


def _server_info(domains: list["Domain"]) -> dict[str, Any]:
    """Collect server information: Python version, Protean version, domains."""
    domain_info = []
    for domain in domains:
        domain_config: dict[str, Any] = {}

        # Extract key config sections
        for section in (
            "databases",
            "brokers",
            "event_store",
            "caches",
            "server",
        ):
            value = domain.config.get(section)
            if value is not None:
                domain_config[section] = sanitize_config(
                    dict(value) if hasattr(value, "items") else value
                )

        # Extract boolean flags
        domain_config["has_outbox"] = getattr(domain, "has_outbox", False)

        domain_info.append(
            {
                "name": domain.name,
                "config": domain_config,
            }
        )

    return {
        "python_version": platform.python_version(),
        "protean_version": protean.__version__,
        "platform": platform.platform(),
        "domains": domain_info,
    }


def _database_status(domain: "Domain") -> dict[str, Any]:
    """Check database provider health."""
    result: dict[str, Any] = {
        "status": "unknown",
        "provider": "none",
        "details": {},
    }

    # Get provider name from config
    db_config = domain.config.get("databases", {})
    if hasattr(db_config, "get"):
        default_config = db_config.get("default", {})
        if hasattr(default_config, "get"):
            result["provider"] = default_config.get("provider", "none")

    try:
        with domain.domain_context():
            provider = domain.providers.get("default")
            if provider is not None:
                result["status"] = "healthy"
            else:
                result["status"] = "not_configured"
    except Exception:
        logger.debug("Failed to check database status", exc_info=True)
        result["status"] = "unhealthy"

    return result


def _broker_status(domain: "Domain") -> dict[str, Any]:
    """Check broker health using health_stats()."""
    result: dict[str, Any] = {
        "status": "unknown",
        "provider": "none",
        "details": {},
    }

    # Get provider name from config
    broker_config = domain.config.get("brokers", {})
    if hasattr(broker_config, "get"):
        default_config = broker_config.get("default", {})
        if hasattr(default_config, "get"):
            result["provider"] = default_config.get("provider", "none")

    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if broker is None:
                result["status"] = "not_configured"
                return result

            stats = broker.health_stats()
            is_connected = stats.get("connected", False)
            details = stats.get("details", {})

            result["status"] = "healthy" if is_connected else "unhealthy"
            result["details"] = {
                "redis_version": details.get("redis_version"),
                "connected_clients": details.get("connected_clients"),
                "used_memory_human": details.get("used_memory_human"),
                "uptime_in_seconds": details.get("uptime_in_seconds"),
                "instantaneous_ops_per_sec": details.get("instantaneous_ops_per_sec"),
                "hit_rate": details.get("hit_rate"),
                "stream_count": (
                    details.get("streams", {}).get("count")
                    if isinstance(details.get("streams"), dict)
                    else None
                ),
                "consumer_group_count": (
                    details.get("consumer_groups", {}).get("count")
                    if isinstance(details.get("consumer_groups"), dict)
                    else None
                ),
            }
    except Exception:
        logger.debug("Failed to check broker status", exc_info=True)
        result["status"] = "unhealthy"

    return result


def _event_store_status(domain: "Domain") -> dict[str, Any]:
    """Check event store health."""
    result: dict[str, Any] = {
        "status": "unknown",
        "provider": "none",
        "details": {},
    }

    # Get provider name from config
    es_config = domain.config.get("event_store", {})
    if hasattr(es_config, "get"):
        result["provider"] = es_config.get("provider", "none")

    try:
        with domain.domain_context():
            store = domain.event_store.store
            if store is not None:
                result["status"] = "healthy"
            else:
                result["status"] = "not_configured"
    except Exception:
        logger.debug("Failed to check event store status", exc_info=True)
        result["status"] = "unhealthy"

    return result


def _cache_status(domain: "Domain") -> dict[str, Any]:
    """Check cache health."""
    result: dict[str, Any] = {
        "status": "unknown",
        "provider": "none",
        "details": {},
    }

    # Get provider name from config
    cache_config = domain.config.get("caches", {})
    if hasattr(cache_config, "get"):
        default_config = cache_config.get("default", {})
        if hasattr(default_config, "get"):
            result["provider"] = default_config.get("provider", "none")

    try:
        with domain.domain_context():
            caches = domain.caches
            if not caches:
                result["status"] = "not_configured"
                return result

            cache = caches.get("default")
            if cache is None:
                result["status"] = "not_configured"
                return result

            # Try ping if available
            if hasattr(cache, "ping"):
                try:
                    cache.ping()
                    result["status"] = "healthy"
                except Exception:
                    result["status"] = "unhealthy"
            else:
                result["status"] = "healthy"
    except Exception:
        logger.debug("Failed to check cache status", exc_info=True)
        result["status"] = "unhealthy"

    return result


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_infrastructure_router(domains: list["Domain"]) -> APIRouter:
    """Create the /infrastructure API router."""
    router = APIRouter()

    @router.get("/infrastructure/status")
    async def infrastructure_status() -> JSONResponse:
        """Full infrastructure status."""
        # Use first domain for connection checks (shared infra)
        domain = domains[0]

        server = _server_info(domains)

        connections: dict[str, Any] = {
            "database": _database_status(domain),
            "broker": _broker_status(domain),
            "event_store": _event_store_status(domain),
            "cache": _cache_status(domain),
        }

        return JSONResponse(
            content={
                "server": server,
                "connections": connections,
            }
        )

    return router
