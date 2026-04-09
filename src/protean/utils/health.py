"""Shared health check utilities for Protean infrastructure components.

Used by both the Engine health server and the FastAPI health router to
avoid duplicating infrastructure probe logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Status constants
STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"


def check_providers(domain: Domain) -> tuple[dict[str, str], bool]:
    """Check database provider connectivity via ``is_alive()``."""
    statuses: dict[str, str] = {}
    all_ok = True
    try:
        for name, provider in domain.providers.items():
            try:
                alive = provider.is_alive()
                statuses[name] = STATUS_OK if alive else STATUS_UNAVAILABLE
                if not alive:
                    all_ok = False
            except Exception:
                logger.debug("Provider %s health check failed", name, exc_info=True)
                statuses[name] = STATUS_UNAVAILABLE
                all_ok = False
    except Exception:
        logger.debug("Error iterating providers", exc_info=True)
        statuses["_error"] = STATUS_UNAVAILABLE
        all_ok = False
    return statuses, all_ok


def check_brokers(domain: Domain) -> tuple[dict[str, str], bool]:
    """Check broker connectivity via ``ping()``."""
    statuses: dict[str, str] = {}
    all_ok = True
    try:
        for name, broker in domain.brokers.items():
            try:
                connected = broker.ping()
                statuses[name] = STATUS_OK if connected else STATUS_UNAVAILABLE
                if not connected:
                    all_ok = False
            except Exception:
                logger.debug("Broker %s health check failed", name, exc_info=True)
                statuses[name] = STATUS_UNAVAILABLE
                all_ok = False
    except Exception:
        logger.debug("Error iterating brokers", exc_info=True)
        statuses["_error"] = STATUS_UNAVAILABLE
        all_ok = False
    return statuses, all_ok


def check_event_store(domain: Domain) -> tuple[str, bool]:
    """Check event store reachability by reading a non-existent stream."""
    try:
        store = domain.event_store.store
        store._read_last_message("__health_check__")
        return STATUS_OK, True
    except Exception:
        logger.debug("Event store health check failed", exc_info=True)
        return STATUS_UNAVAILABLE, False


def check_caches(domain: Domain) -> tuple[dict[str, str], bool]:
    """Check cache connectivity."""
    statuses: dict[str, str] = {}
    all_ok = True
    try:
        for name, cache in domain.caches.items():
            try:
                if hasattr(cache, "ping"):
                    ok = cache.ping()
                    statuses[name] = STATUS_OK if ok else STATUS_UNAVAILABLE
                    if not ok:
                        all_ok = False
                else:
                    statuses[name] = STATUS_OK
            except Exception:
                logger.debug("Cache %s health check failed", name, exc_info=True)
                statuses[name] = STATUS_UNAVAILABLE
                all_ok = False
    except Exception:
        logger.debug("Error iterating caches", exc_info=True)
        statuses["_error"] = STATUS_UNAVAILABLE
        all_ok = False
    return statuses, all_ok
