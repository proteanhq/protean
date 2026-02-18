"""REST API endpoints for the Protean Observatory.

Provides JSON snapshot endpoints for infrastructure health, outbox status,
stream information, aggregated statistics, and trace history. These power the
dashboard and can be consumed by external monitoring tools.
"""

import json
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from protean.domain import Domain

from ..tracing import TRACE_STREAM

logger = logging.getLogger(__name__)

# Window string → milliseconds mapping
_WINDOW_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
}

# Error event types for error rate calculation
_ERROR_EVENTS = {"handler.failed", "message.dlq"}


def _get_redis(domains: List[Domain]):
    """Get a Redis connection from the first domain's broker."""
    for d in domains:
        try:
            with d.domain_context():
                broker = d.brokers.get("default")
                if broker and hasattr(broker, "redis_instance"):
                    return broker.redis_instance
        except Exception:
            continue
    return None


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


def _decode_stream_id(stream_id) -> str:
    """Decode a Redis stream ID that may be bytes or str."""
    if isinstance(stream_id, bytes):
        return stream_id.decode("utf-8")
    return str(stream_id)


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
                    "redis": {
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

    @router.get("/traces")
    async def traces(
        count: int = Query(200, ge=1, le=1000, description="Number of traces"),
        domain: Optional[str] = Query(None, description="Filter by domain"),
        stream: Optional[str] = Query(None, description="Filter by stream"),
        event: Optional[str] = Query(None, description="Filter by event type"),
        message_id: Optional[str] = Query(
            None, description="Filter by message ID (lifecycle lookup)"
        ),
    ):
        """Recent trace history from the persisted Redis Stream."""
        redis_conn = _get_redis(domains)
        if not redis_conn:
            return JSONResponse(
                content={"traces": [], "count": 0, "error": "Redis not available"},
                status_code=503,
            )

        has_filters = domain or stream or event or message_id

        try:
            # XREVRANGE returns newest-first; fetch extra to account for filtering
            # message_id lookups scan wider since lifecycle events may be sparse
            if message_id:
                fetch_count = 5000
            elif has_filters:
                fetch_count = count * 3
            else:
                fetch_count = count
            raw_entries = redis_conn.xrevrange(
                TRACE_STREAM, count=min(fetch_count, 5000)
            )
        except Exception as e:
            logger.error(f"Error reading trace stream: {e}", exc_info=True)
            return JSONResponse(
                content={"traces": [], "count": 0, "error": "Failed to read traces"},
                status_code=500,
            )

        result = []
        for stream_id, fields in raw_entries:
            try:
                data_raw = fields.get(b"data") or fields.get("data")
                if not data_raw:
                    continue
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode("utf-8")
                trace = json.loads(data_raw)

                # Apply filters
                if domain and trace.get("domain") != domain:
                    continue
                if stream and trace.get("stream") != stream:
                    continue
                if event and trace.get("event") != event:
                    continue
                if message_id and trace.get("message_id") != message_id:
                    continue

                trace["_stream_id"] = _decode_stream_id(stream_id)
                result.append(trace)

                # message_id lookups return all matching events (no count limit)
                if not message_id and len(result) >= count:
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        return JSONResponse(content={"traces": result, "count": len(result)})

    @router.get("/traces/stats")
    async def traces_stats(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
    ):
        """Aggregated trace statistics for a time window."""
        window_ms = _WINDOW_MS.get(window)
        if window_ms is None:
            valid = ", ".join(_WINDOW_MS.keys())
            return JSONResponse(
                content={"error": f"Invalid window: {window}. Use {valid}."},
                status_code=400,
            )

        redis_conn = _get_redis(domains)
        if not redis_conn:
            return JSONResponse(
                content={"error": "Redis not available"}, status_code=503
            )

        # Redis stream IDs are timestamp-based: <ms>-<seq>
        min_id = str(int(time.time() * 1000) - window_ms)

        try:
            raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
        except Exception as e:
            logger.error(f"Error reading trace stream for stats: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to read traces"}, status_code=500
            )

        counts: dict[str, int] = {}
        error_count = 0
        total = 0
        latency_sum = 0.0
        latency_count = 0

        for _, fields in raw_entries:
            try:
                data_raw = fields.get(b"data") or fields.get("data")
                if not data_raw:
                    continue
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode("utf-8")
                trace = json.loads(data_raw)

                event_type = trace.get("event", "unknown")
                counts[event_type] = counts.get(event_type, 0) + 1
                total += 1

                if event_type in _ERROR_EVENTS:
                    error_count += 1

                duration = trace.get("duration_ms")
                if event_type == "handler.completed" and duration is not None:
                    latency_sum += float(duration)
                    latency_count += 1
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        error_rate = round((error_count / total * 100), 2) if total > 0 else 0.0
        avg_latency_ms = (
            round(latency_sum / latency_count, 2) if latency_count > 0 else 0.0
        )

        return JSONResponse(
            content={
                "window": window,
                "counts": counts,
                "error_count": error_count,
                "error_rate": error_rate,
                "avg_latency_ms": avg_latency_ms,
                "total": total,
            }
        )

    @router.delete("/traces")
    async def delete_traces():
        """Clear all persisted trace history."""
        redis_conn = _get_redis(domains)
        if not redis_conn:
            return JSONResponse(
                content={"error": "Redis not available"}, status_code=503
            )

        try:
            deleted = redis_conn.delete(TRACE_STREAM)
            return JSONResponse(content={"status": "ok", "deleted": bool(deleted)})
        except Exception as e:
            logger.error(f"Error deleting trace stream: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to delete traces"}, status_code=500
            )

    return router
