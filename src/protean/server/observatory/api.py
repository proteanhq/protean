"""REST API endpoints for the Protean Observatory.

Provides JSON snapshot endpoints for infrastructure health, outbox status,
stream information, and aggregated statistics. These power the dashboard's
infrastructure panel and can be consumed by external monitoring tools.
"""

import logging
from typing import List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from protean.domain import Domain

logger = logging.getLogger(__name__)


def _outbox_status(domain: Domain) -> dict:
    """Query outbox counts for a domain."""
    try:
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")
            counts = outbox_repo.count_by_status()
            return {"status": "ok", "counts": counts}
    except Exception as e:
        logger.error(f"Error querying outbox for {domain.name}: {e}", exc_info=True)
        return {"status": "error", "error": "Failed to query outbox"}


def _broker_health(domain: Domain) -> dict:
    """Query broker health stats for a domain using the public port API."""
    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if broker is None:
                return {"status": "error", "error": "No default broker configured"}
            stats = broker.health_stats()
            return {"status": "ok", **stats}
    except Exception as e:
        logger.error(f"Error querying broker for {domain.name}: {e}", exc_info=True)
        return {"status": "error", "error": "Failed to query broker health"}


def _broker_info(domain: Domain) -> dict:
    """Query broker consumer group info for a domain using the public port API."""
    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if broker is None:
                return {"status": "error", "error": "No default broker configured"}
            info = broker.info()
            return {"status": "ok", **info}
    except Exception as e:
        logger.error(
            f"Error querying broker info for {domain.name}: {e}", exc_info=True
        )
        return {"status": "error", "error": "Failed to query broker info"}


def create_api_router(domains: List[Domain]) -> APIRouter:
    """Create the REST API router for observatory endpoints."""
    router = APIRouter()

    @router.get("/health")
    async def health():
        """Infrastructure health check."""
        # Use first domain's broker for health (they typically share infrastructure)
        broker_stats = _broker_health(domains[0])

        # Public health_stats() returns {"status", "connected", "details": {...}}
        broker_details = broker_stats.get("details", {})
        is_connected = broker_stats.get("connected", False)

        return JSONResponse(
            content={
                "status": broker_stats.get("status", "unhealthy"),
                "domains": [d.name for d in domains],
                "infrastructure": {
                    "broker": {
                        "healthy": is_connected
                        and broker_details.get("healthy", False),
                        "version": broker_details.get("redis_version", "unknown"),
                        "connected_clients": broker_details.get("connected_clients", 0),
                        "memory": broker_details.get("used_memory_human", "0B"),
                        "uptime_seconds": broker_details.get("uptime_in_seconds", 0),
                        "ops_per_sec": broker_details.get(
                            "instantaneous_ops_per_sec", 0
                        ),
                    },
                },
            }
        )

    @router.get("/outbox")
    async def outbox():
        """Outbox status for all domains."""
        result = {}
        for domain in domains:
            result[domain.name] = _outbox_status(domain)
        return JSONResponse(content=result)

    @router.get("/streams")
    async def streams():
        """Stream lengths and consumer group info."""
        # Use first domain's broker (shared infrastructure)
        broker_stats = _broker_health(domains[0])
        broker_info_data = _broker_info(domains[0])

        broker_details = broker_stats.get("details", {})

        return JSONResponse(
            content={
                "message_counts": broker_details.get("message_counts", {}),
                "streams": broker_details.get("streams", {}),
                "consumer_groups": broker_info_data.get("consumer_groups", {}),
            }
        )

    @router.get("/stats")
    async def stats():
        """Aggregated throughput and error rate statistics."""
        # Combine outbox and stream metrics
        outbox_data = {}
        for domain in domains:
            outbox_data[domain.name] = _outbox_status(domain)

        broker_stats = _broker_health(domains[0])
        broker_details = broker_stats.get("details", {})

        return JSONResponse(
            content={
                "outbox": outbox_data,
                "message_counts": broker_details.get("message_counts", {}),
                "streams": broker_details.get("streams", {}),
            }
        )

    return router
