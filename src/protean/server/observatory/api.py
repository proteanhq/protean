"""REST API endpoints for the Protean Observatory.

Provides JSON snapshot endpoints for infrastructure health, outbox status,
stream information, aggregated statistics, and trace history. These power the
dashboard and can be consumed by external monitoring tools.
"""

import json
import logging
import time
from typing import List, Optional, Tuple

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from protean.domain import Domain

from ..tracing import TRACE_STREAM

logger = logging.getLogger(__name__)

# Internal streams that should be excluded from Observatory metrics
_INTERNAL_STREAMS = {TRACE_STREAM}

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

# Worker throughput settings
_WORKER_THROUGHPUT_WINDOW_S = 300  # 5 minutes
_WORKER_THROUGHPUT_BUCKET_S = 10  # 10-second buckets

# Worker status thresholds (milliseconds)
_WORKER_ACTIVE_THRESHOLD_MS = 5 * 60 * 1000  # 5 min
_WORKER_IDLE_THRESHOLD_MS = 30 * 60 * 1000  # 30 min


def _parse_worker_key(consumer_name: str) -> Tuple[str, str]:
    """Extract (hostname, pid) from a consumer name.

    Consumer names follow the pattern: {ClassName}-{hostname}-{pid}-{random_hex}
    where:
    - ClassName: subscriber class (no hyphens)
    - hostname: Docker container ID or hostname (may contain hyphens)
    - pid: numeric process ID
    - random_hex: 6 hex characters

    Strategy: split from the right — last segment is random_hex,
    second-to-last is pid (numeric), remaining middle is hostname.
    """
    parts = consumer_name.rsplit("-", 2)
    if len(parts) >= 3:
        prefix = parts[0]  # ClassName-hostname (possibly with hyphens)
        pid = parts[1]
        # random_hex = parts[2]

        # pid must be numeric; if not, fall back
        if pid.isdigit():
            # prefix = "ClassName-hostname" — strip the class name
            # Class name is the first segment before the first hyphen
            first_hyphen = prefix.find("-")
            if first_hyphen != -1:
                hostname = prefix[first_hyphen + 1 :]
                return (hostname, pid)

    # Fallback: use entire consumer name as worker_id
    return (consumer_name, "0")


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


def _discover_streams(redis_conn) -> list:
    """Discover all application streams in Redis.

    The Observatory process doesn't subscribe to streams itself, so the
    broker's ``_get_streams_to_check()`` returns an empty set.  Instead we
    scan Redis for keys of type ``stream`` and filter out internal ones
    (e.g. the trace stream).
    """
    if redis_conn is None:
        return []
    try:
        streams = []
        cursor = 0
        while True:
            cursor, keys = redis_conn.scan(cursor=cursor, count=200, _type="stream")
            for key in keys:
                name = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                if name not in _INTERNAL_STREAMS:
                    streams.append(name)
            if cursor == 0:
                break
        return sorted(streams)
    except Exception as e:
        logger.debug(f"Error discovering streams from Redis: {e}")
        return []


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
        redis_conn = _get_redis(domains)
        stream_names = _discover_streams(redis_conn) if redis_conn else []

        message_counts = {"total_messages": 0, "in_flight": 0, "failed": 0, "dlq": 0}
        consumer_groups = {}

        for name in stream_names:
            try:
                message_counts["total_messages"] += redis_conn.xlen(name)
                groups_info = redis_conn.xinfo_groups(name)
                for g in groups_info:
                    if isinstance(g, dict):
                        gname = g.get("name") or g.get(b"name")
                        if isinstance(gname, bytes):
                            gname = gname.decode("utf-8")
                        gpending = g.get("pending") or g.get(b"pending") or 0
                        glag = g.get("lag") or g.get(b"lag") or 0
                        message_counts["in_flight"] += int(gpending)
                        consumer_groups[str(gname)] = {
                            "stream": name,
                            "pending": int(gpending),
                            "lag": int(glag),
                        }
            except Exception:
                pass

        return JSONResponse(
            content={
                "message_counts": message_counts,
                "streams": {"count": len(stream_names), "names": stream_names},
                "consumer_groups": consumer_groups,
            }
        )

    @router.get("/consumers")
    async def consumers():
        """Per-consumer breakdown across all streams and consumer groups.

        Calls ``XINFO CONSUMERS`` for each (stream, group) pair to show
        per-worker pending counts and idle time — the key data needed to
        verify that multiple worker instances are sharing the load.
        """
        redis_conn = _get_redis(domains)
        if not redis_conn:
            return JSONResponse(
                content={
                    "consumers": [],
                    "count": 0,
                    "error": "Redis not available",
                },
                status_code=503,
            )

        stream_names = _discover_streams(redis_conn)
        result = []

        for stream_name in stream_names:
            try:
                groups = redis_conn.xinfo_groups(stream_name)
                for g in groups:
                    if not isinstance(g, dict):
                        continue
                    gname = g.get("name") or g.get(b"name")
                    if isinstance(gname, bytes):
                        gname = gname.decode("utf-8")
                    if not gname:
                        continue

                    try:
                        consumers_info = redis_conn.xinfo_consumers(stream_name, gname)
                        for c in consumers_info:
                            if not isinstance(c, dict):
                                continue
                            cname = c.get("name") or c.get(b"name")
                            if isinstance(cname, bytes):
                                cname = cname.decode("utf-8")
                            cpending = c.get("pending") or c.get(b"pending") or 0
                            cidle = c.get("idle") or c.get(b"idle") or 0
                            result.append(
                                {
                                    "consumer_name": str(cname),
                                    "group": str(gname),
                                    "stream": stream_name,
                                    "pending": int(cpending),
                                    "idle_ms": int(cidle),
                                }
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        return JSONResponse(content={"consumers": result, "count": len(result)})

    @router.get("/workers")
    async def workers():
        """Engine worker (pod) overview with per-worker throughput sparklines.

        Groups Redis consumers by engine instance (hostname + pid) and computes
        per-worker throughput from the trace stream. Each worker represents one
        engine process (container/pod) that may run multiple subscriptions.
        """
        redis_conn = _get_redis(domains)
        if not redis_conn:
            return JSONResponse(
                content={
                    "workers": [],
                    "count": 0,
                    "error": "Redis not available",
                },
                status_code=503,
            )

        # 1. Collect all consumers (same logic as /api/consumers)
        stream_names = _discover_streams(redis_conn)
        all_consumers = []

        for stream_name in stream_names:
            try:
                groups = redis_conn.xinfo_groups(stream_name)
                for g in groups:
                    if not isinstance(g, dict):
                        continue
                    gname = g.get("name") or g.get(b"name")
                    if isinstance(gname, bytes):
                        gname = gname.decode("utf-8")
                    if not gname:
                        continue

                    try:
                        consumers_info = redis_conn.xinfo_consumers(stream_name, gname)
                        for c in consumers_info:
                            if not isinstance(c, dict):
                                continue
                            cname = c.get("name") or c.get(b"name")
                            if isinstance(cname, bytes):
                                cname = cname.decode("utf-8")
                            cpending = c.get("pending") or c.get(b"pending") or 0
                            cidle = c.get("idle") or c.get(b"idle") or 0
                            all_consumers.append(
                                {
                                    "consumer_name": str(cname),
                                    "group": str(gname),
                                    "stream": stream_name,
                                    "pending": int(cpending),
                                    "idle_ms": int(cidle),
                                }
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. Group consumers by worker key (hostname, pid)
        worker_map: dict[str, dict] = {}
        for consumer in all_consumers:
            hostname, pid = _parse_worker_key(consumer["consumer_name"])
            worker_id = f"{hostname}-{pid}"

            if worker_id not in worker_map:
                worker_map[worker_id] = {
                    "worker_id": worker_id,
                    "hostname": hostname,
                    "pid": int(pid) if pid.isdigit() else 0,
                    "subscriptions": [],
                    "subscription_count": 0,
                    "total_pending": 0,
                    "min_idle_ms": float("inf"),
                    "_domains": set(),
                    "_streams": set(),
                }

            w = worker_map[worker_id]
            w["subscriptions"].append(consumer)
            w["subscription_count"] += 1
            w["total_pending"] += consumer["pending"]
            w["min_idle_ms"] = min(w["min_idle_ms"], consumer["idle_ms"])

            # Extract engine domain from group (module path), e.g.
            # "inventory.projections.inventory_level.InventoryLevelProjector" → "inventory"
            # "protean.server.engine.Commands:..." → skip (command dispatcher)
            group = consumer["group"]
            if not group.startswith("protean."):
                engine_domain = group.split(".")[0]
                w["_domains"].add(engine_domain)
            w["_streams"].add(consumer["stream"])

        # 3. Finalize domain and streams
        for w in worker_map.values():
            w["domain"] = ", ".join(sorted(w.pop("_domains")))
            w["streams"] = sorted(w.pop("_streams"))

        # 4. Compute per-worker throughput from trace stream
        now_ms = int(time.time() * 1000)
        window_ms = _WORKER_THROUGHPUT_WINDOW_S * 1000
        bucket_ms = _WORKER_THROUGHPUT_BUCKET_S * 1000
        bucket_count = _WORKER_THROUGHPUT_WINDOW_S // _WORKER_THROUGHPUT_BUCKET_S
        min_id = str(now_ms - window_ms)

        # Initialize throughput buckets per worker
        throughput: dict[str, list[int]] = {}
        for wid in worker_map:
            throughput[wid] = [0] * bucket_count

        try:
            raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
            for stream_id, fields in raw_entries:
                try:
                    data_raw = fields.get(b"data") or fields.get("data")
                    if not data_raw:
                        continue
                    if isinstance(data_raw, bytes):
                        data_raw = data_raw.decode("utf-8")
                    trace = json.loads(data_raw)

                    if trace.get("event") != "handler.completed":
                        continue

                    trace_worker_id = trace.get("worker_id")
                    if not trace_worker_id:
                        continue

                    # Map trace worker_id (subscription ID) to worker key
                    t_hostname, t_pid = _parse_worker_key(trace_worker_id)
                    t_worker_id = f"{t_hostname}-{t_pid}"

                    if t_worker_id not in throughput:
                        continue

                    # Determine bucket from stream ID timestamp
                    sid = _decode_stream_id(stream_id)
                    ts_ms = int(sid.split("-")[0])
                    bucket_idx = (ts_ms - (now_ms - window_ms)) // bucket_ms
                    if 0 <= bucket_idx < bucket_count:
                        throughput[t_worker_id][bucket_idx] += 1
                except (json.JSONDecodeError, TypeError, ValueError, IndexError):
                    continue
        except Exception as e:
            logger.debug(f"Error reading traces for worker throughput: {e}")

        # 5. Merge throughput into worker objects and compute status
        for wid, w in worker_map.items():
            counts = throughput.get(wid, [0] * bucket_count)
            total = sum(counts)
            w["throughput"] = {
                "window_seconds": _WORKER_THROUGHPUT_WINDOW_S,
                "bucket_seconds": _WORKER_THROUGHPUT_BUCKET_S,
                "counts": counts,
                "total": total,
            }

            # Status: use throughput as primary signal (if processing, it's active),
            # fall back to idle_ms from XINFO CONSUMERS
            if total > 0:
                w["status"] = "active"
            elif w["min_idle_ms"] < _WORKER_ACTIVE_THRESHOLD_MS:
                w["status"] = "active"
            elif w["min_idle_ms"] < _WORKER_IDLE_THRESHOLD_MS:
                w["status"] = "idle"
            else:
                w["status"] = "offline"

        workers_list = sorted(
            worker_map.values(),
            key=lambda w: (w["domain"], w["status"] != "active", w["hostname"]),
        )

        return JSONResponse(
            content={
                "workers": workers_list,
                "count": len(workers_list),
                "timestamp": now_ms,
            }
        )

    @router.get("/queue-depth")
    async def queue_depth():
        """Queue depth snapshot for backpressure visualization.

        Returns outbox pending counts per domain, per-stream XLEN,
        and per-consumer-group XPENDING in a single response optimized
        for dashboard polling.
        """
        result = {
            "timestamp": time.time() * 1000,
            "outbox": {},
            "streams": {},
            "totals": {
                "outbox_pending": 0,
                "stream_depth": 0,
                "consumer_pending": 0,
            },
        }

        # 1. Outbox counts per domain
        for domain in domains:
            outbox_data = _outbox_status(domain)
            if outbox_data.get("status") == "ok":
                counts = outbox_data["counts"]
                result["outbox"][domain.name] = counts
                result["totals"]["outbox_pending"] += counts.get("pending", 0)
                result["totals"]["outbox_pending"] += counts.get("processing", 0)

        # 2. Per-stream depth + per-consumer-group lag
        #    stream_depth  = max lag across all consumer groups per stream
        #                    (the actual unconsumed backlog, NOT total XLEN)
        #    consumer_pending = messages delivered but not yet ACK'd (in-flight)
        redis_conn = _get_redis(domains)
        if redis_conn:
            for stream_name in _discover_streams(redis_conn):
                try:
                    xlen = redis_conn.xlen(stream_name)
                    stream_entry = {
                        "length": xlen,
                        "consumer_groups": {},
                    }
                    max_lag = 0

                    try:
                        groups = redis_conn.xinfo_groups(stream_name)
                        for g in groups:
                            if isinstance(g, dict):
                                gname = g.get("name") or g.get(b"name")
                                if isinstance(gname, bytes):
                                    gname = gname.decode("utf-8")
                                gpending = g.get("pending") or g.get(b"pending") or 0
                                glag = g.get("lag") or g.get(b"lag") or 0
                                stream_entry["consumer_groups"][str(gname)] = {
                                    "pending": int(gpending),
                                    "lag": int(glag),
                                }
                                result["totals"]["consumer_pending"] += int(gpending)
                                max_lag = max(max_lag, int(glag))
                    except Exception:
                        pass

                    result["totals"]["stream_depth"] += max_lag
                    result["streams"][stream_name] = stream_entry
                except Exception:
                    pass

        return JSONResponse(content=result)

    @router.get("/stats")
    async def stats():
        """Aggregated throughput and error rate statistics."""
        outbox_data = {}
        for domain in domains:
            outbox_data[domain.name] = _outbox_status(domain)

        redis_conn = _get_redis(domains)
        stream_names = _discover_streams(redis_conn) if redis_conn else []

        message_counts = {"total_messages": 0, "in_flight": 0, "failed": 0, "dlq": 0}
        for name in stream_names:
            try:
                message_counts["total_messages"] += redis_conn.xlen(name)
                groups_info = redis_conn.xinfo_groups(name)
                for g in groups_info:
                    if isinstance(g, dict):
                        gpending = g.get("pending") or g.get(b"pending") or 0
                        message_counts["in_flight"] += int(gpending)
            except Exception:
                pass

        return JSONResponse(
            content={
                "outbox": outbox_data,
                "message_counts": message_counts,
                "streams": {"count": len(stream_names), "names": stream_names},
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

    @router.get("/subscriptions")
    async def subscriptions():
        """Subscription lag status for all domains.

        Returns per-subscription lag, pending count, DLQ depth, and
        overall summary for each monitored domain.
        """
        from protean.server.subscription_status import collect_subscription_statuses

        result = {}
        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                result[domain.name] = {
                    "status": "ok",
                    "subscriptions": [s.to_dict() for s in statuses],
                    "summary": {
                        "total": len(statuses),
                        "ok": sum(1 for s in statuses if s.status == "ok"),
                        "lagging": sum(1 for s in statuses if s.status == "lagging"),
                        "unknown": sum(1 for s in statuses if s.status == "unknown"),
                        "total_lag": sum(s.lag or 0 for s in statuses),
                        "total_pending": sum(s.pending for s in statuses),
                        "total_dlq": sum(s.dlq_depth for s in statuses),
                    },
                }
            except Exception as e:
                logger.error(
                    f"Error collecting subscription status for {domain.name}: {e}",
                    exc_info=True,
                )
                result[domain.name] = {
                    "status": "error",
                    "error": "Failed to collect subscription status",
                }

        return JSONResponse(content=result)

    # ------------------------------------------------------------------
    # DLQ Management Endpoints
    # ------------------------------------------------------------------

    @router.get("/dlq")
    async def dlq_list(
        subscription: Optional[str] = Query(
            None, description="Filter by stream category"
        ),
        limit: int = Query(100, ge=1, le=1000, description="Maximum entries"),
    ):
        """List DLQ messages across all subscriptions."""
        from protean.port.broker import BrokerCapabilities
        from protean.utils.dlq import collect_dlq_streams, discover_subscriptions

        domain = domains[0]
        try:
            with domain.domain_context():
                broker = domain.brokers.get("default")
                if broker is None:
                    return JSONResponse(
                        content={"error": "No default broker configured"},
                        status_code=503,
                    )
                if not broker.has_capability(BrokerCapabilities.DEAD_LETTER_QUEUE):
                    return JSONResponse(
                        content={"error": "Broker does not support DLQ"},
                        status_code=501,
                    )

                if subscription:
                    infos = discover_subscriptions(domain)
                    dlq_streams = []
                    for info in infos:
                        if info.stream_category == subscription:
                            dlq_streams.append(info.dlq_stream)
                            if info.backfill_dlq_stream:
                                dlq_streams.append(info.backfill_dlq_stream)
                    if not dlq_streams:
                        return JSONResponse(
                            content={"error": f"No subscription for '{subscription}'"},
                            status_code=404,
                        )
                else:
                    dlq_streams = collect_dlq_streams(domain)

                entries = broker.dlq_list(dlq_streams, limit=limit)
                return JSONResponse(
                    content={
                        "entries": [
                            {
                                "dlq_id": e.dlq_id,
                                "original_id": e.original_id,
                                "stream": e.stream,
                                "consumer_group": e.consumer_group,
                                "failure_reason": e.failure_reason,
                                "failed_at": e.failed_at,
                                "retry_count": e.retry_count,
                                "dlq_stream": e.dlq_stream,
                            }
                            for e in entries
                        ],
                        "count": len(entries),
                    }
                )
        except Exception as e:
            logger.error(f"Error listing DLQ: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to list DLQ messages"},
                status_code=500,
            )

    @router.get("/dlq/{dlq_id}")
    async def dlq_inspect(dlq_id: str):
        """Inspect a single DLQ message with full payload."""
        from protean.port.broker import BrokerCapabilities
        from protean.utils.dlq import collect_dlq_streams

        domain = domains[0]
        try:
            with domain.domain_context():
                broker = domain.brokers.get("default")
                if broker is None or not broker.has_capability(
                    BrokerCapabilities.DEAD_LETTER_QUEUE
                ):
                    return JSONResponse(
                        content={"error": "DLQ not available"},
                        status_code=503,
                    )

                dlq_streams = collect_dlq_streams(domain)
                for dlq_stream in dlq_streams:
                    entry = broker.dlq_inspect(dlq_stream, dlq_id)
                    if entry:
                        # Strip internal DLQ metadata from displayed payload
                        payload = {
                            k: v
                            for k, v in entry.payload.items()
                            if k != "_dlq_metadata"
                        }
                        return JSONResponse(
                            content={
                                "dlq_id": entry.dlq_id,
                                "original_id": entry.original_id,
                                "stream": entry.stream,
                                "consumer_group": entry.consumer_group,
                                "failure_reason": entry.failure_reason,
                                "failed_at": entry.failed_at,
                                "retry_count": entry.retry_count,
                                "dlq_stream": entry.dlq_stream,
                                "payload": payload,
                            }
                        )

                return JSONResponse(
                    content={"error": f"DLQ message '{dlq_id}' not found"},
                    status_code=404,
                )
        except Exception as e:
            logger.error(f"Error inspecting DLQ message: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to inspect DLQ message"},
                status_code=500,
            )

    @router.post("/dlq/{dlq_id}/replay")
    async def dlq_replay(dlq_id: str):
        """Replay a single DLQ message back to its original stream."""
        from protean.port.broker import BrokerCapabilities
        from protean.utils.dlq import collect_dlq_streams

        domain = domains[0]
        try:
            with domain.domain_context():
                broker = domain.brokers.get("default")
                if broker is None or not broker.has_capability(
                    BrokerCapabilities.DEAD_LETTER_QUEUE
                ):
                    return JSONResponse(
                        content={"error": "DLQ not available"},
                        status_code=503,
                    )

                dlq_streams = collect_dlq_streams(domain)
                for dlq_stream in dlq_streams:
                    entry = broker.dlq_inspect(dlq_stream, dlq_id)
                    if entry:
                        success = broker.dlq_replay(dlq_stream, dlq_id, entry.stream)
                        if success:
                            return JSONResponse(
                                content={
                                    "status": "ok",
                                    "replayed": True,
                                    "target_stream": entry.stream,
                                }
                            )
                        return JSONResponse(
                            content={"error": "Replay failed"},
                            status_code=500,
                        )

                return JSONResponse(
                    content={"error": f"DLQ message '{dlq_id}' not found"},
                    status_code=404,
                )
        except Exception as e:
            logger.error(f"Error replaying DLQ message: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to replay DLQ message"},
                status_code=500,
            )

    @router.post("/dlq/replay-all")
    async def dlq_replay_all(
        subscription: str = Query(..., description="Stream category (required)"),
    ):
        """Replay all DLQ messages for a subscription."""
        from protean.port.broker import BrokerCapabilities
        from protean.utils.dlq import discover_subscriptions

        domain = domains[0]
        try:
            with domain.domain_context():
                broker = domain.brokers.get("default")
                if broker is None or not broker.has_capability(
                    BrokerCapabilities.DEAD_LETTER_QUEUE
                ):
                    return JSONResponse(
                        content={"error": "DLQ not available"},
                        status_code=503,
                    )

                infos = discover_subscriptions(domain)
                dlq_streams = []
                for info in infos:
                    if info.stream_category == subscription:
                        dlq_streams.append(info.dlq_stream)
                        if info.backfill_dlq_stream:
                            dlq_streams.append(info.backfill_dlq_stream)

                if not dlq_streams:
                    return JSONResponse(
                        content={"error": f"No subscription for '{subscription}'"},
                        status_code=404,
                    )

                total = 0
                for dlq_stream in dlq_streams:
                    total += broker.dlq_replay_all(dlq_stream, subscription)

                return JSONResponse(
                    content={
                        "status": "ok",
                        "replayed": total,
                        "target_stream": subscription,
                    }
                )
        except Exception as e:
            logger.error(f"Error replaying all DLQ messages: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to replay DLQ messages"},
                status_code=500,
            )

    @router.delete("/dlq")
    async def dlq_purge(
        subscription: str = Query(..., description="Stream category (required)"),
    ):
        """Purge all DLQ messages for a subscription."""
        from protean.port.broker import BrokerCapabilities
        from protean.utils.dlq import discover_subscriptions

        domain = domains[0]
        try:
            with domain.domain_context():
                broker = domain.brokers.get("default")
                if broker is None or not broker.has_capability(
                    BrokerCapabilities.DEAD_LETTER_QUEUE
                ):
                    return JSONResponse(
                        content={"error": "DLQ not available"},
                        status_code=503,
                    )

                infos = discover_subscriptions(domain)
                dlq_streams = []
                for info in infos:
                    if info.stream_category == subscription:
                        dlq_streams.append(info.dlq_stream)
                        if info.backfill_dlq_stream:
                            dlq_streams.append(info.backfill_dlq_stream)

                if not dlq_streams:
                    return JSONResponse(
                        content={"error": f"No subscription for '{subscription}'"},
                        status_code=404,
                    )

                total = 0
                for dlq_stream in dlq_streams:
                    total += broker.dlq_purge(dlq_stream)

                return JSONResponse(content={"status": "ok", "purged": total})
        except Exception as e:
            logger.error(f"Error purging DLQ: {e}", exc_info=True)
            return JSONResponse(
                content={"error": "Failed to purge DLQ"},
                status_code=500,
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
