"""REST API endpoints for the Protean Observatory.

Provides JSON snapshot endpoints for infrastructure health, outbox status,
stream information, aggregated statistics, and trace history. These power the
dashboard and can be consumed by external monitoring tools.
"""

import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from protean.domain import Domain
from protean.port.broker import BrokerCapabilities

from .._redis import redis_client
from ..tracing import TRACE_STREAM, decode_trace, trace_number

if TYPE_CHECKING:
    import redis

    from protean.infra.broker import Broker

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

# Success event types for timeline aggregation
_SUCCESS_EVENTS = {"handler.completed", "message.handled"}

# Window → bucket width in milliseconds for timeline aggregation
_TIMELINE_BUCKET_MS = {
    "5m": 10_000,  # 10s  → 31 buckets
    "15m": 30_000,  # 30s  → 31 buckets
    "1h": 120_000,  # 2min → 31 buckets
    "24h": 3_600_000,  # 1hr  → 25 buckets
    "7d": 21_600_000,  # 6hr  → 29 buckets
}

# Worker throughput settings
_WORKER_THROUGHPUT_WINDOW_S = 300  # 5 minutes
_WORKER_THROUGHPUT_BUCKET_S = 10  # 10-second buckets

# Worker status thresholds (milliseconds)
_WORKER_ACTIVE_THRESHOLD_MS = 5 * 60 * 1000  # 5 min
_WORKER_IDLE_THRESHOLD_MS = 30 * 60 * 1000  # 30 min


def _parse_worker_key(consumer_name: str) -> tuple[str, str]:
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


def _get_redis(domains: list[Domain]) -> "redis.Redis[Any] | None":
    """Get a Redis connection from the first domain's broker."""
    for d in domains:
        try:
            with d.domain_context():
                broker = d.brokers.get("default")
                client = redis_client(broker)
                if client is not None:
                    return client
        except Exception:  # try the next domain; logged at debug
            logger.debug(
                "Could not get the Redis broker of domain %s", d.name, exc_info=True
            )
            continue
    return None


def _discover_streams(redis_conn: "redis.Redis[Any] | None") -> list[str]:
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
    except Exception as e:  # noqa: BLE001 - scrape: show no streams when Redis fails
        logger.debug(f"Error discovering streams from Redis: {e}")
        return []


def _outbox_status(domain: Domain) -> dict[str, Any]:
    """Query outbox counts for a domain."""
    try:
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")
            counts = outbox_repo.count_by_status()
            return {"status": "ok", "counts": counts}
    except Exception:  # an outbox error becomes an error status; logged
        logger.exception(f"Error querying outbox for {domain.name}")
        return {"status": "error", "error": "Failed to query outbox"}


def _broker_health(domain: Domain) -> dict[str, Any]:
    """Query broker health stats for a domain using the public port API."""
    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if broker is None:
                return {"status": "error", "error": "No default broker configured"}
            stats = broker.health()
            return {"status": "ok", **stats}
    except Exception:  # any broker error becomes an error status; logged
        logger.exception(f"Error querying broker for {domain.name}")
        return {"status": "error", "error": "Failed to query broker health"}


def _broker_info(domain: Domain) -> dict[str, Any]:
    """Query broker consumer group info for a domain using the public port API."""
    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if broker is None:
                return {"status": "error", "error": "No default broker configured"}
            return {"status": "ok", "consumer_groups": broker._consumer_groups()}
    except Exception:  # any broker error becomes an error status; logged
        logger.exception(f"Error querying broker info for {domain.name}")
        return {"status": "error", "error": "Failed to query broker info"}


def _decode_stream_id(stream_id: object) -> str:
    """Decode a Redis stream ID that may be bytes or str."""
    if isinstance(stream_id, bytes):
        return stream_id.decode("utf-8")
    return str(stream_id)


# redis-py 7.3.0 resolves ``xinfo_groups``/``xinfo_consumers`` (via its command
# mixin MRO) to an untyped ``def (name: Any) -> Any`` overload, so mypy --strict
# reports ``no-untyped-call`` at every call site even though the source is
# annotated. These thin wrappers isolate that external typing defect behind a
# single disclosed ``cast`` and give callers a concrete ``list[Any]`` result
# (the ``XINFO`` commands return a list of field-value mappings).
def _xinfo_groups(redis_conn: "redis.Redis[Any]", name: str) -> list[Any]:
    """Return ``XINFO GROUPS`` output for a stream as a list."""
    # redis-py's MRO resolves ``xinfo_groups`` to an untyped overload; binding
    # the method to an ``Any`` first sidesteps mypy's ``no-untyped-call`` for
    # this external typing defect without a mode-dependent ``type: ignore``.
    xinfo: Any = redis_conn.xinfo_groups
    return cast("list[Any]", xinfo(name))


def _xinfo_consumers(
    redis_conn: "redis.Redis[Any]", name: str, groupname: str
) -> list[Any]:
    """Return ``XINFO CONSUMERS`` output for a (stream, group) as a list."""
    # See ``_xinfo_groups`` — same external redis-py typing defect.
    xinfo: Any = redis_conn.xinfo_consumers
    return cast("list[Any]", xinfo(name, groupname))


# Cache for the combined overview scan to avoid redundant XRANGE calls.
# TTL is shorter than the 5s poller interval so data stays fresh but back-to-back
# requests (e.g. window change triggering multiple pollers) are served instantly.
_OVERVIEW_CACHE_TTL_S = 3.0

# Window → cached (stored-at time, overview body); one per router.
_OverviewCache = dict[str, tuple[float, dict[str, Any]]]


def _xinfo_field(entry: dict[Any, Any], key: str) -> Any:
    """Return ``key`` from an ``XINFO`` entry, whose keys may be str or bytes."""
    return entry.get(key) or entry.get(key.encode())


def _xinfo_name(entry: dict[Any, Any]) -> Any:
    """Return the ``name`` of an ``XINFO`` entry, decoded when it is bytes."""
    name = _xinfo_field(entry, "name")
    if isinstance(name, bytes):
        name = name.decode("utf-8")
    return name


def _xinfo_count(entry: dict[Any, Any], key: str) -> int:
    """Return a numeric ``XINFO`` field as an int, 0 when it is missing."""
    return int(_xinfo_field(entry, key) or 0)


def _redis_unavailable(content: dict[str, Any]) -> JSONResponse:
    """Return the 503 response an endpoint sends when Redis is not reachable."""
    return JSONResponse(content=content, status_code=503)


# ----------------------------------------------------------------------
# /health, /outbox
# ----------------------------------------------------------------------


def _health(domains: list[Domain]) -> JSONResponse:
    # Use first domain's broker for health (they typically share infrastructure)
    broker_stats = _broker_health(domains[0])

    # Public health() returns {"status", "connected", "details": {...}}
    broker_details = broker_stats.get("details", {})
    is_connected = broker_stats.get("connected", False)

    return JSONResponse(
        content={
            "status": broker_stats.get("status", "unhealthy"),
            "domains": [d.name for d in domains],
            "infrastructure": {
                "redis": {
                    "healthy": is_connected and broker_details.get("healthy", False),
                    "version": broker_details.get("redis_version", "unknown"),
                    "connected_clients": broker_details.get("connected_clients", 0),
                    "memory": broker_details.get("used_memory_human", "0B"),
                    "uptime_seconds": broker_details.get("uptime_in_seconds", 0),
                    "ops_per_sec": broker_details.get("instantaneous_ops_per_sec", 0),
                },
            },
        }
    )


def _outbox(domains: list[Domain]) -> JSONResponse:
    result: dict[str, Any] = {}
    for domain in domains:
        result[domain.name] = _outbox_status(domain)
    return JSONResponse(content=result)


# ----------------------------------------------------------------------
# /streams, /stats
# ----------------------------------------------------------------------


def _count_stream(
    redis_conn: "redis.Redis[Any]",
    name: str,
    message_counts: dict[str, int],
    consumer_groups: dict[str, dict[str, Any]] | None,
) -> None:
    """Add one stream's length and group pending counts to the running totals.

    When ``consumer_groups`` is given, each group is also recorded in it by name.
    """
    try:
        message_counts["total_messages"] += redis_conn.xlen(name)
        for g in _xinfo_groups(redis_conn, name):
            if isinstance(g, dict):
                # When groups are recorded (/streams), read the name before
                # counting: a name that fails to decode skips the rest of the
                # stream without counting this group. /stats reads no names.
                gname = None if consumer_groups is None else str(_xinfo_name(g))
                gpending = _xinfo_count(g, "pending")
                message_counts["in_flight"] += gpending
                if consumer_groups is not None:
                    consumer_groups[str(gname)] = {
                        "stream": name,
                        "pending": gpending,
                        "lag": _xinfo_count(g, "lag"),
                    }
    except Exception:  # one unreadable stream must not fail the endpoint
        logger.debug("Could not read stream %s", name, exc_info=True)


def _message_counts(
    redis_conn: "redis.Redis[Any] | None",
    stream_names: list[str],
    consumer_groups: dict[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Return the message counts across ``stream_names``.

    When ``consumer_groups`` is given, it is filled with every group read.
    """
    message_counts = {"total_messages": 0, "in_flight": 0, "failed": 0, "dlq": 0}
    if redis_conn is not None:
        for name in stream_names:
            _count_stream(redis_conn, name, message_counts, consumer_groups)
    return message_counts


def _streams(domains: list[Domain]) -> JSONResponse:
    redis_conn = _get_redis(domains)
    stream_names = _discover_streams(redis_conn) if redis_conn else []
    consumer_groups: dict[str, dict[str, Any]] = {}
    message_counts = _message_counts(redis_conn, stream_names, consumer_groups)

    return JSONResponse(
        content={
            "message_counts": message_counts,
            "streams": {"count": len(stream_names), "names": stream_names},
            "consumer_groups": consumer_groups,
        }
    )


def _stats(domains: list[Domain]) -> JSONResponse:
    outbox_data: dict[str, Any] = {}
    for domain in domains:
        outbox_data[domain.name] = _outbox_status(domain)

    redis_conn = _get_redis(domains)
    stream_names = _discover_streams(redis_conn) if redis_conn else []
    message_counts = _message_counts(redis_conn, stream_names)

    return JSONResponse(
        content={
            "outbox": outbox_data,
            "message_counts": message_counts,
            "streams": {"count": len(stream_names), "names": stream_names},
        }
    )


# ----------------------------------------------------------------------
# /consumers, /workers
# ----------------------------------------------------------------------


def _consumer_row(
    consumer: dict[Any, Any], group: str, stream_name: str
) -> dict[str, Any]:
    """Build one consumer row from an ``XINFO CONSUMERS`` entry."""
    return {
        "consumer_name": str(_xinfo_name(consumer)),
        "group": group,
        "stream": stream_name,
        "pending": _xinfo_count(consumer, "pending"),
        "idle_ms": _xinfo_count(consumer, "idle"),
    }


def _collect_group_consumers(
    redis_conn: "redis.Redis[Any]",
    stream_name: str,
    group: str,
    rows: list[dict[str, Any]],
) -> None:
    """Append a row per consumer of one (stream, group) to ``rows``."""
    try:
        rows.extend(
            _consumer_row(c, group, stream_name)
            for c in _xinfo_consumers(redis_conn, stream_name, group)
            if isinstance(c, dict)
        )
    except Exception:  # one unreadable group must not drop the others
        logger.debug(
            "Could not read consumers of group %s on stream %s",
            group,
            stream_name,
            exc_info=True,
        )


def _collect_stream_consumers(
    redis_conn: "redis.Redis[Any]", stream_name: str, rows: list[dict[str, Any]]
) -> None:
    """Append a row per consumer of every group on one stream to ``rows``."""
    try:
        for g in _xinfo_groups(redis_conn, stream_name):
            if not isinstance(g, dict):
                continue
            gname = _xinfo_name(g)
            if gname:
                _collect_group_consumers(redis_conn, stream_name, str(gname), rows)
    except Exception:  # one unreadable stream must not fail the endpoint
        logger.debug("Could not read groups of stream %s", stream_name, exc_info=True)


def _collect_consumers(redis_conn: "redis.Redis[Any]") -> list[dict[str, Any]]:
    """Return a row per consumer across all streams and consumer groups."""
    rows: list[dict[str, Any]] = []
    for stream_name in _discover_streams(redis_conn):
        _collect_stream_consumers(redis_conn, stream_name, rows)
    return rows


def _consumers(domains: list[Domain]) -> JSONResponse:
    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable(
            {"consumers": [], "count": 0, "error": "Redis not available"}
        )

    result = _collect_consumers(redis_conn)
    return JSONResponse(content={"consumers": result, "count": len(result)})


def _new_worker(worker_id: str, hostname: str, pid: str) -> dict[str, Any]:
    """Return an empty worker record for the worker ``hostname``-``pid``."""
    return {
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


def _add_consumer_to_worker(w: dict[str, Any], consumer: dict[str, Any]) -> None:
    """Add one consumer row's subscription, counts, domain and stream to a worker."""
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


def _group_workers(consumers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group consumer rows by worker key (hostname, pid)."""
    worker_map: dict[str, dict[str, Any]] = {}
    for consumer in consumers:
        hostname, pid = _parse_worker_key(consumer["consumer_name"])
        worker_id = f"{hostname}-{pid}"
        if worker_id not in worker_map:
            worker_map[worker_id] = _new_worker(worker_id, hostname, pid)
        _add_consumer_to_worker(worker_map[worker_id], consumer)

    for w in worker_map.values():
        w["domain"] = ", ".join(sorted(w.pop("_domains")))
        w["streams"] = sorted(w.pop("_streams"))
    return worker_map


def _trace_worker_key(trace: dict[str, Any] | None) -> str | None:
    """Return the worker key of a ``handler.completed`` trace, else None."""
    if trace is None or trace.get("event") != "handler.completed":
        return None

    trace_worker_id = trace.get("worker_id")
    if not trace_worker_id or not isinstance(trace_worker_id, str):
        return None

    # Map trace worker_id (subscription ID) to worker key
    t_hostname, t_pid = _parse_worker_key(trace_worker_id)
    return f"{t_hostname}-{t_pid}"


def _worker_throughput(
    redis_conn: "redis.Redis[Any]", worker_ids: list[str], now_ms: int
) -> dict[str, list[int]]:
    """Count each worker's completed handlers per bucket over the throughput window."""
    window_ms = _WORKER_THROUGHPUT_WINDOW_S * 1000
    bucket_ms = _WORKER_THROUGHPUT_BUCKET_S * 1000
    bucket_count = _WORKER_THROUGHPUT_WINDOW_S // _WORKER_THROUGHPUT_BUCKET_S
    min_id = str(now_ms - window_ms)

    # Initialize throughput buckets per worker
    throughput: dict[str, list[int]] = {}
    for wid in worker_ids:
        throughput[wid] = [0] * bucket_count

    try:
        raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
    except Exception:  # scrape: show zero throughput without traces
        logger.debug("Could not read traces for worker throughput", exc_info=True)
        raw_entries = []

    for stream_id, fields in raw_entries:
        t_worker_id = _trace_worker_key(decode_trace(fields))
        if t_worker_id not in throughput:
            continue

        # Determine bucket from stream ID timestamp
        sid = _decode_stream_id(stream_id)
        ts_ms = int(sid.split("-")[0])
        bucket_idx = (ts_ms - (now_ms - window_ms)) // bucket_ms
        if 0 <= bucket_idx < bucket_count:
            throughput[t_worker_id][bucket_idx] += 1

    return throughput


def _worker_status(total: int, min_idle_ms: float) -> str:
    """Return ``active``, ``idle`` or ``offline`` for a worker."""
    # Status: use throughput as primary signal (if processing, it's active),
    # fall back to idle_ms from XINFO CONSUMERS
    if total > 0 or min_idle_ms < _WORKER_ACTIVE_THRESHOLD_MS:
        return "active"
    if min_idle_ms < _WORKER_IDLE_THRESHOLD_MS:
        return "idle"
    return "offline"


def _workers(domains: list[Domain]) -> JSONResponse:
    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable(
            {"workers": [], "count": 0, "error": "Redis not available"}
        )

    worker_map = _group_workers(_collect_consumers(redis_conn))

    now_ms = int(time.time() * 1000)
    bucket_count = _WORKER_THROUGHPUT_WINDOW_S // _WORKER_THROUGHPUT_BUCKET_S
    throughput = _worker_throughput(redis_conn, list(worker_map), now_ms)

    # Merge throughput into worker objects and compute status
    for wid, w in worker_map.items():
        counts = throughput.get(wid, [0] * bucket_count)
        total = sum(counts)
        w["throughput"] = {
            "window_seconds": _WORKER_THROUGHPUT_WINDOW_S,
            "bucket_seconds": _WORKER_THROUGHPUT_BUCKET_S,
            "counts": counts,
            "total": total,
        }
        w["status"] = _worker_status(total, w["min_idle_ms"])

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


# ----------------------------------------------------------------------
# /queue-depth
# ----------------------------------------------------------------------


def _add_outbox_depth(domains: list[Domain], result: dict[str, Any]) -> None:
    """Add each domain's outbox counts and pending total to ``result``."""
    for domain in domains:
        outbox_data = _outbox_status(domain)
        if outbox_data.get("status") == "ok":
            counts = outbox_data["counts"]
            result["outbox"][domain.name] = counts
            result["totals"]["outbox_pending"] += counts.get("pending", 0)
            result["totals"]["outbox_pending"] += counts.get("processing", 0)


def _add_group_depths(
    redis_conn: "redis.Redis[Any]",
    stream_name: str,
    stream_entry: dict[str, Any],
    totals: dict[str, Any],
) -> int:
    """Add each group's pending and lag on one stream, and return the max lag."""
    max_lag = 0
    try:
        for g in _xinfo_groups(redis_conn, stream_name):
            if isinstance(g, dict):
                gpending = _xinfo_count(g, "pending")
                glag = _xinfo_count(g, "lag")
                stream_entry["consumer_groups"][str(_xinfo_name(g))] = {
                    "pending": gpending,
                    "lag": glag,
                }
                totals["consumer_pending"] += gpending
                max_lag = max(max_lag, glag)
    # keep the stream entry without group data; logged
    except Exception:
        logger.debug("Could not read groups of stream %s", stream_name, exc_info=True)
    return max_lag


def _add_stream_depth(
    redis_conn: "redis.Redis[Any]", stream_name: str, result: dict[str, Any]
) -> None:
    """Add one stream's length, group lag and pending counts to ``result``."""
    try:
        stream_entry: dict[str, Any] = {
            "length": redis_conn.xlen(stream_name),
            "consumer_groups": {},
        }
        max_lag = _add_group_depths(
            redis_conn, stream_name, stream_entry, result["totals"]
        )
        result["totals"]["stream_depth"] += max_lag
        result["streams"][stream_name] = stream_entry
    except Exception:  # one unreadable stream must not fail the endpoint
        logger.debug("Could not read stream %s", stream_name, exc_info=True)


def _queue_depth(domains: list[Domain]) -> JSONResponse:
    result: dict[str, Any] = {
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
    _add_outbox_depth(domains, result)

    # 2. Per-stream depth + per-consumer-group lag
    #    stream_depth  = max lag across all consumer groups per stream
    #                    (the actual unconsumed backlog, NOT total XLEN)
    #    consumer_pending = messages delivered but not yet ACK'd (in-flight)
    redis_conn = _get_redis(domains)
    if redis_conn:
        for stream_name in _discover_streams(redis_conn):
            _add_stream_depth(redis_conn, stream_name, result)

    return JSONResponse(content=result)


# ----------------------------------------------------------------------
# /traces
# ----------------------------------------------------------------------


def _trace_matches(trace: dict[str, Any], filters: dict[str, str | None]) -> bool:
    """Return whether ``trace`` equals every filter that has a value."""
    return all(not value or trace.get(key) == value for key, value in filters.items())


def _trace_fetch_count(count: int, message_id: str | None, has_filters: bool) -> int:
    """Return how many trace entries to read for a ``/traces`` request."""
    # XREVRANGE returns newest-first; fetch extra to account for filtering
    # message_id lookups scan wider since lifecycle events may be sparse
    if message_id:
        fetch_count = 5000
    elif has_filters:
        fetch_count = count * 3
    else:
        fetch_count = count
    return min(fetch_count, 5000)


def _traces(
    domains: list[Domain],
    count: int,
    domain: str | None,
    stream: str | None,
    event: str | None,
    message_id: str | None,
) -> JSONResponse:
    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable(
            {"traces": [], "count": 0, "error": "Redis not available"}
        )

    filters = {
        "domain": domain,
        "stream": stream,
        "event": event,
        "message_id": message_id,
    }
    has_filters = any(filters.values())

    try:
        raw_entries = redis_conn.xrevrange(
            TRACE_STREAM, count=_trace_fetch_count(count, message_id, has_filters)
        )
    except Exception:  # any read error becomes a 500 response; logged
        logger.exception("Error reading trace stream")
        return JSONResponse(
            content={"traces": [], "count": 0, "error": "Failed to read traces"},
            status_code=500,
        )

    result: list[dict[str, Any]] = []
    for stream_id, fields in raw_entries:
        trace = decode_trace(fields)
        if trace is None or not _trace_matches(trace, filters):
            continue

        trace["_stream_id"] = _decode_stream_id(stream_id)
        result.append(trace)

        # message_id lookups return all matching events (no count limit)
        if not message_id and len(result) >= count:
            break

    return JSONResponse(content={"traces": result, "count": len(result)})


def _invalid_window(window: str) -> JSONResponse:
    """Return the 400 response for a window that is not in ``_WINDOW_MS``."""
    valid = ", ".join(_WINDOW_MS.keys())
    return JSONResponse(
        content={"error": f"Invalid window: {window}. Use {valid}."},
        status_code=400,
    )


def _timeline_buckets(
    now_ms: int, window_ms: int, bucket_ms: int
) -> dict[int, dict[str, int]]:
    """Return an empty bucket for every ``bucket_ms`` step of the window."""
    window_start = (now_ms - window_ms) // bucket_ms * bucket_ms
    buckets: dict[int, dict[str, int]] = {}
    t = window_start
    while t <= now_ms:
        buckets[t] = {"time_ms": t, "total": 0, "success": 0, "errors": 0}
        t += bucket_ms
    return buckets


def _add_to_bucket(
    buckets: dict[int, dict[str, int]],
    bucket_ms: int,
    stream_id: object,
    event_type: str,
) -> None:
    """Count one trace in the timeline bucket its stream ID falls in."""
    sid = _decode_stream_id(stream_id)
    ts_ms = int(sid.split("-")[0])
    bucket_key = ts_ms // bucket_ms * bucket_ms
    bucket = buckets.get(bucket_key)
    if bucket is not None:
        bucket["total"] += 1
        if event_type in _SUCCESS_EVENTS:
            bucket["success"] += 1
        elif event_type in _ERROR_EVENTS:
            bucket["errors"] += 1


def _overview_stats(
    raw_entries: list[Any], buckets: dict[int, dict[str, int]], bucket_ms: int
) -> dict[str, Any]:
    """Count events, errors and latency in one pass, filling ``buckets`` as well."""
    counts: dict[str, int] = {}
    error_count = 0
    total = 0
    latency_sum = 0.0
    latency_count = 0

    for stream_id, fields in raw_entries:
        trace = decode_trace(fields)
        if trace is None:
            continue

        event_type = trace.get("event", "unknown")
        if not isinstance(event_type, str):
            continue

        counts[event_type] = counts.get(event_type, 0) + 1
        total += 1
        if event_type in _ERROR_EVENTS:
            error_count += 1
        duration = trace_number(trace.get("duration_ms"))
        if event_type == "handler.completed" and duration is not None:
            latency_sum += duration
            latency_count += 1

        _add_to_bucket(buckets, bucket_ms, stream_id, event_type)

    error_rate = round((error_count / total * 100), 2) if total > 0 else 0.0
    avg_latency_ms = round(latency_sum / latency_count, 2) if latency_count > 0 else 0.0
    return {
        "counts": counts,
        "error_count": error_count,
        "error_rate": error_rate,
        "avg_latency_ms": avg_latency_ms,
        "total": total,
    }


def _traces_overview(
    domains: list[Domain], cache: _OverviewCache, window: str
) -> JSONResponse:
    window_ms = _WINDOW_MS.get(window)
    if window_ms is None:
        return _invalid_window(window)

    # Check cache
    now = time.time()
    cached = cache.get(window)
    if cached and (now - cached[0]) < _OVERVIEW_CACHE_TTL_S:
        return JSONResponse(content=cached[1])

    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable({"error": "Redis not available"})

    now_ms = int(now * 1000)
    min_id = str(now_ms - window_ms)
    bucket_ms = _TIMELINE_BUCKET_MS[window]

    try:
        raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
    except Exception:  # any read error becomes a 500 response; logged
        logger.exception("Error reading trace stream")
        return JSONResponse(content={"error": "Failed to read traces"}, status_code=500)

    buckets = _timeline_buckets(now_ms, window_ms, bucket_ms)
    stats = _overview_stats(raw_entries, buckets, bucket_ms)

    result: dict[str, Any] = {
        "window": window,
        # Stats
        **stats,
        # Timeline
        "bucket_ms": bucket_ms,
        "buckets": sorted(buckets.values(), key=lambda b: b["time_ms"]),
    }

    # Update cache (use current time, not the pre-scan `now`)
    cache[window] = (time.time(), result)

    return JSONResponse(content=result)


def _overview_part(
    domains: list[Domain], cache: _OverviewCache, window: str, keys: tuple[str, ...]
) -> JSONResponse:
    """Return the ``keys`` of the overview body, or the overview's error response."""
    overview = _traces_overview(domains, cache, window)
    body = json.loads(bytes(overview.body).decode())
    if "error" in body:
        return overview
    return JSONResponse(content={key: body[key] for key in keys})


def _traces_stats(
    domains: list[Domain], cache: _OverviewCache, window: str
) -> JSONResponse:
    return _overview_part(
        domains,
        cache,
        window,
        ("window", "counts", "error_count", "error_rate", "avg_latency_ms", "total"),
    )


def _traces_timeline(
    domains: list[Domain], cache: _OverviewCache, window: str
) -> JSONResponse:
    return _overview_part(domains, cache, window, ("window", "bucket_ms", "buckets"))


def _failed_trace_range(
    window: str, start: str | None, end: str | None
) -> tuple[str, str] | JSONResponse:
    """Return the (min, max) stream IDs to read, or a 400 response."""
    if start and end:
        # Custom range: parse ISO 8601 timestamps
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            return (
                str(int(start_dt.timestamp() * 1000)),
                str(int(end_dt.timestamp() * 1000)),
            )
        except (ValueError, TypeError):
            return JSONResponse(
                content={"error": "Invalid date format. Use ISO 8601."},
                status_code=400,
            )

    window_ms = _WINDOW_MS.get(window)
    if window_ms is None:
        return _invalid_window(window)
    return str(int(time.time() * 1000) - window_ms), "+"


def _failed_traces(
    raw_entries: list[Any], filters: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Return the failed and DLQ traces that match ``filters``, oldest first."""
    matches: list[dict[str, Any]] = []
    for stream_id, fields in raw_entries:
        trace = decode_trace(fields)
        if trace is None:
            continue

        event_type = trace.get("event", "")
        if not isinstance(event_type, str) or event_type not in _ERROR_EVENTS:
            continue

        # Apply optional filters
        if not _trace_matches(trace, filters):
            continue

        trace["_stream_id"] = _decode_stream_id(stream_id)
        matches.append(trace)
    return matches


def _traces_failed(
    domains: list[Domain],
    window: str,
    handler: str | None,
    message_type: str | None,
    limit: int,
    offset: int,
    start: str | None,
    end: str | None,
) -> JSONResponse:
    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable(
            {"traces": [], "total_count": 0, "error": "Redis not available"}
        )

    # Determine time range
    id_range = _failed_trace_range(window, start, end)
    if isinstance(id_range, JSONResponse):
        return id_range
    min_id, max_id = id_range

    try:
        raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id, max=max_id)
    except Exception:  # any read error becomes a 500 response; logged
        logger.exception("Error reading trace stream for failed traces")
        return JSONResponse(
            content={
                "traces": [],
                "total_count": 0,
                "error": "Failed to read traces",
            },
            status_code=500,
        )

    # Collect all matching entries (for total count + pagination)
    all_matches = _failed_traces(
        raw_entries, {"handler": handler, "message_type": message_type}
    )

    # Sort newest first, then paginate
    all_matches.reverse()
    total_count = len(all_matches)
    page = all_matches[offset : offset + limit]

    return JSONResponse(content={"traces": page, "total_count": total_count})


def _trace_detail(domains: list[Domain], stream_id: str) -> JSONResponse:
    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable({"error": "Redis not available"})

    try:
        entries = redis_conn.xrange(TRACE_STREAM, min=stream_id, max=stream_id)
    except Exception:  # any read error becomes a 500 response; logged
        logger.exception(f"Error reading trace {stream_id}")
        return JSONResponse(content={"error": "Failed to read trace"}, status_code=500)

    if not entries:
        return JSONResponse(content={"error": "Trace not found"}, status_code=404)

    _, fields = entries[0]
    trace = decode_trace(fields)
    if trace is None:
        return JSONResponse(
            content={"error": "Failed to parse trace data"}, status_code=500
        )
    trace["_stream_id"] = stream_id
    return JSONResponse(content=trace)


def _delete_traces(domains: list[Domain]) -> JSONResponse:
    redis_conn = _get_redis(domains)
    if not redis_conn:
        return _redis_unavailable({"error": "Redis not available"})

    try:
        deleted = redis_conn.delete(TRACE_STREAM)
        return JSONResponse(content={"status": "ok", "deleted": bool(deleted)})
    except Exception:  # a Redis delete error becomes a 500 response; logged
        logger.exception("Error deleting trace stream")
        return JSONResponse(
            content={"error": "Failed to delete traces"}, status_code=500
        )


# ----------------------------------------------------------------------
# /subscriptions
# ----------------------------------------------------------------------


def _subscription_summary(statuses: list[Any]) -> dict[str, Any]:
    """Return the totals of a domain's subscription statuses."""
    return {
        "total": len(statuses),
        "ok": sum(1 for s in statuses if s.status == "ok"),
        "lagging": sum(1 for s in statuses if s.status == "lagging"),
        "unknown": sum(1 for s in statuses if s.status == "unknown"),
        "total_lag": sum(s.lag or 0 for s in statuses),
        "total_pending": sum(s.pending for s in statuses),
        "total_dlq": sum(s.dlq_depth for s in statuses),
    }


def _domain_subscriptions(domain: Domain) -> dict[str, Any]:
    """Return one domain's subscription statuses and summary, or an error status."""
    from protean.server.subscription_status import (  # noqa: PLC0415
        collect_subscription_statuses,
    )

    try:
        statuses = collect_subscription_statuses(domain)
        return {
            "status": "ok",
            "subscriptions": [s.to_dict() for s in statuses],
            "summary": _subscription_summary(statuses),
        }
    except Exception:  # one domain's error must not hide the others; logged
        logger.exception(f"Error collecting subscription status for {domain.name}")
        return {
            "status": "error",
            "error": "Failed to collect subscription status",
        }


def _subscriptions(domains: list[Domain]) -> JSONResponse:
    result: dict[str, Any] = {}
    for domain in domains:
        result[domain.name] = _domain_subscriptions(domain)
    return JSONResponse(content=result)


# ----------------------------------------------------------------------
# /dlq
# ----------------------------------------------------------------------


def _subscription_dlq_streams(domain: Domain, subscription: str) -> list[str]:
    """Return the DLQ streams (and backfill DLQ streams) of one stream category."""
    from protean.utils.dlq import discover_subscriptions  # noqa: PLC0415

    dlq_streams: list[str] = []
    for info in discover_subscriptions(domain):
        if info.stream_category == subscription:
            dlq_streams.append(info.dlq_stream)
            if info.backfill_dlq_stream:
                dlq_streams.append(info.backfill_dlq_stream)
    return dlq_streams


def _no_subscription(subscription: str) -> JSONResponse:
    """Return the 404 response for a stream category with no subscription."""
    return JSONResponse(
        content={"error": f"No subscription for '{subscription}'"},
        status_code=404,
    )


def _dlq_broker(domain: Domain) -> "Broker | None":
    """Return the default broker when it supports dead-letter queues, else None."""
    broker = domain.brokers.get("default")
    if (
        broker is None
        or BrokerCapabilities.DEAD_LETTER_QUEUE not in broker.capabilities
    ):
        return None
    return broker


def _dlq_entry_fields(entry: Any) -> dict[str, Any]:
    """Return the fields of a DLQ entry that the DLQ endpoints show."""
    return {
        "dlq_id": entry.dlq_id,
        "original_id": entry.original_id,
        "stream": entry.stream,
        "consumer_group": entry.consumer_group,
        "failure_reason": entry.failure_reason,
        "failed_at": entry.failed_at,
        "retry_count": entry.retry_count,
        "dlq_stream": entry.dlq_stream,
    }


def _dlq_list_streams(domain: Domain, subscription: str | None) -> list[str] | None:
    """Return the DLQ streams to list, or None for a category with no subscription."""
    from protean.utils.dlq import collect_dlq_streams  # noqa: PLC0415

    if subscription:
        return _subscription_dlq_streams(domain, subscription) or None
    return collect_dlq_streams(domain)


def _dlq_list(
    domains: list[Domain], subscription: str | None, limit: int, offset: int
) -> JSONResponse:
    domain = domains[0]
    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if broker is None:
                return JSONResponse(
                    content={"error": "No default broker configured"},
                    status_code=503,
                )
            if BrokerCapabilities.DEAD_LETTER_QUEUE not in broker.capabilities:
                return JSONResponse(
                    content={"error": "Broker does not support DLQ"},
                    status_code=501,
                )

            dlq_streams = _dlq_list_streams(domain, subscription)
            if dlq_streams is None:
                return _no_subscription(str(subscription))

            # Fetch all entries (broker sorts newest first)
            all_entries = broker.dlq_list(dlq_streams, limit=10000)
            total_count = len(all_entries)
            page = all_entries[offset : offset + limit]

            return JSONResponse(
                content={
                    "entries": [_dlq_entry_fields(e) for e in page],
                    "total_count": total_count,
                }
            )
    except Exception:  # any DLQ error becomes a 500 response; logged
        logger.exception("Error listing DLQ")
        return JSONResponse(
            content={"error": "Failed to list DLQ messages"},
            status_code=500,
        )


def _dlq_not_available() -> JSONResponse:
    """Return the 503 response for a broker without dead-letter-queue support."""
    return JSONResponse(content={"error": "DLQ not available"}, status_code=503)


def _dlq_not_found(dlq_id: str) -> JSONResponse:
    """Return the 404 response for a DLQ message that no DLQ stream holds."""
    return JSONResponse(
        content={"error": f"DLQ message '{dlq_id}' not found"},
        status_code=404,
    )


def _dlq_get(domains: list[Domain], dlq_id: str) -> JSONResponse:
    from protean.utils.dlq import collect_dlq_streams  # noqa: PLC0415

    domain = domains[0]
    try:
        with domain.domain_context():
            broker = _dlq_broker(domain)
            if broker is None:
                return _dlq_not_available()

            for dlq_stream in collect_dlq_streams(domain):
                entry = broker.dlq_get(dlq_stream, dlq_id)
                if entry:
                    # Strip internal DLQ metadata from displayed payload
                    payload = {
                        k: v for k, v in entry.payload.items() if k != "_dlq_metadata"
                    }
                    return JSONResponse(
                        content={**_dlq_entry_fields(entry), "payload": payload}
                    )

            return _dlq_not_found(dlq_id)
    except Exception:  # any DLQ error becomes a 500 response; logged
        logger.exception("Error inspecting DLQ message")
        return JSONResponse(
            content={"error": "Failed to inspect DLQ message"},
            status_code=500,
        )


def _replay_entry(
    broker: Any, dlq_stream: str, dlq_id: str, target_stream: str
) -> JSONResponse:
    """Replay one DLQ message to ``target_stream`` and return the response."""
    if broker.dlq_replay(dlq_stream, dlq_id, target_stream):
        return JSONResponse(
            content={
                "status": "ok",
                "replayed": True,
                "target_stream": target_stream,
            }
        )
    return JSONResponse(content={"error": "Replay failed"}, status_code=500)


def _dlq_replay(domains: list[Domain], dlq_id: str) -> JSONResponse:
    from protean.utils.dlq import collect_dlq_streams  # noqa: PLC0415

    domain = domains[0]
    try:
        with domain.domain_context():
            broker = _dlq_broker(domain)
            if broker is None:
                return _dlq_not_available()

            for dlq_stream in collect_dlq_streams(domain):
                entry = broker.dlq_get(dlq_stream, dlq_id)
                if entry:
                    return _replay_entry(broker, dlq_stream, dlq_id, entry.stream)

            return _dlq_not_found(dlq_id)
    except Exception:  # any DLQ error becomes a 500 response; logged
        logger.exception("Error replaying DLQ message")
        return JSONResponse(
            content={"error": "Failed to replay DLQ message"},
            status_code=500,
        )


def _dlq_replay_all(domains: list[Domain], subscription: str) -> JSONResponse:
    domain = domains[0]
    try:
        with domain.domain_context():
            broker = _dlq_broker(domain)
            if broker is None:
                return _dlq_not_available()

            dlq_streams = _subscription_dlq_streams(domain, subscription)
            if not dlq_streams:
                return _no_subscription(subscription)

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
    except Exception:  # any DLQ error becomes a 500 response; logged
        logger.exception("Error replaying all DLQ messages")
        return JSONResponse(
            content={"error": "Failed to replay DLQ messages"},
            status_code=500,
        )


def _dlq_purge(domains: list[Domain], subscription: str) -> JSONResponse:
    domain = domains[0]
    try:
        with domain.domain_context():
            broker = _dlq_broker(domain)
            if broker is None:
                return _dlq_not_available()

            dlq_streams = _subscription_dlq_streams(domain, subscription)
            if not dlq_streams:
                return _no_subscription(subscription)

            total = 0
            for dlq_stream in dlq_streams:
                total += broker.dlq_purge(dlq_stream)

            return JSONResponse(content={"status": "ok", "purged": total})
    except Exception:  # any DLQ error becomes a 500 response; logged
        logger.exception("Error purging DLQ")
        return JSONResponse(
            content={"error": "Failed to purge DLQ"},
            status_code=500,
        )


# ----------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------


def create_api_router(domains: list[Domain]) -> APIRouter:
    """Create the REST API router for observatory endpoints."""
    router = APIRouter()
    # Each router keeps its own overview cache.
    overview_cache: _OverviewCache = {}

    # Each route is a thin wrapper around a module-level function. FastAPI
    # builds the operationId from the wrapper's name and the description from
    # its docstring, and `domains` must stay out of the signature, or FastAPI
    # would read it from the query string.

    @router.get("/health")
    async def health() -> JSONResponse:
        """Infrastructure health check."""
        return _health(domains)

    @router.get("/outbox")
    async def outbox() -> JSONResponse:
        """Outbox status for all domains."""
        return _outbox(domains)

    @router.get("/streams")
    async def streams() -> JSONResponse:
        """Stream lengths and consumer group info."""
        return _streams(domains)

    @router.get("/consumers")
    async def consumers() -> JSONResponse:
        """Per-consumer breakdown across all streams and consumer groups.

        Calls ``XINFO CONSUMERS`` for each (stream, group) pair to show
        per-worker pending counts and idle time — the key data needed to
        verify that multiple worker instances are sharing the load.
        """
        return _consumers(domains)

    @router.get("/workers")
    async def workers() -> JSONResponse:
        """Engine worker (pod) overview with per-worker throughput sparklines.

        Groups Redis consumers by engine instance (hostname + pid) and computes
        per-worker throughput from the trace stream. Each worker represents one
        engine process (container/pod) that may run multiple subscriptions.
        """
        return _workers(domains)

    @router.get("/queue-depth")
    async def queue_depth() -> JSONResponse:
        """Queue depth snapshot for backpressure visualization.

        Returns outbox pending counts per domain, per-stream XLEN,
        and per-consumer-group XPENDING in a single response optimized
        for dashboard polling.
        """
        return _queue_depth(domains)

    @router.get("/stats")
    async def stats() -> JSONResponse:
        """Outbox status, stream message counts and stream names."""
        return _stats(domains)

    @router.get("/traces")
    async def traces(
        count: int = Query(200, ge=1, le=1000, description="Number of traces"),
        domain: str | None = Query(None, description="Filter by domain"),
        stream: str | None = Query(None, description="Filter by stream"),
        event: str | None = Query(None, description="Filter by event type"),
        message_id: str | None = Query(
            None, description="Filter by message ID (lifecycle lookup)"
        ),
    ) -> JSONResponse:
        """Recent trace history from the persisted Redis Stream."""
        return _traces(domains, count, domain, stream, event, message_id)

    @router.get("/traces/stats")
    async def traces_stats(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
    ) -> JSONResponse:
        """Aggregated trace statistics for a time window.

        Delegates to the combined /traces/overview endpoint and returns
        only the stats portion for backward compatibility.
        """
        return _traces_stats(domains, overview_cache, window)

    @router.get("/traces/timeline")
    async def traces_timeline(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
    ) -> JSONResponse:
        """Pre-aggregated activity timeline buckets for the full time window.

        Delegates to the combined /traces/overview endpoint and returns
        only the timeline portion for backward compatibility.
        """
        return _traces_timeline(domains, overview_cache, window)

    @router.get("/traces/overview")
    async def traces_overview(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
    ) -> JSONResponse:
        """Combined stats + timeline in a single XRANGE scan.

        Returns event counts, error rate, avg latency, AND pre-aggregated
        timeline buckets.  The frontend calls this once instead of two
        separate endpoints, halving Redis scan time for large windows.
        Results are cached for 3 seconds to avoid redundant scans from
        near-simultaneous requests.
        """
        return _traces_overview(domains, overview_cache, window)

    @router.get("/traces/failed")
    async def traces_failed(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
        handler: str | None = Query(None, description="Filter by handler name"),
        message_type: str | None = Query(None, description="Filter by message type"),
        limit: int = Query(25, ge=1, le=200, description="Page size"),
        offset: int = Query(0, ge=0, description="Number of entries to skip"),
        start: str | None = Query(None, description="Custom range start (ISO 8601)"),
        end: str | None = Query(None, description="Custom range end (ISO 8601)"),
    ) -> JSONResponse:
        """Failed and DLQ traces filtered by time window.

        Returns only handler.failed and message.dlq trace events,
        with optional filtering by handler name and message type.
        Supports offset-based pagination via offset/limit params.
        """
        return _traces_failed(
            domains, window, handler, message_type, limit, offset, start, end
        )

    @router.get("/traces/{stream_id}")
    async def trace_detail(stream_id: str) -> JSONResponse:
        """Fetch a single trace event by its Redis stream ID."""
        return _trace_detail(domains, stream_id)

    @router.get("/subscriptions")
    async def subscriptions() -> JSONResponse:
        """Subscription lag status for all domains.

        Returns per-subscription lag, pending count, DLQ depth, and
        overall summary for each monitored domain.
        """
        return _subscriptions(domains)

    # ------------------------------------------------------------------
    # DLQ Management Endpoints
    # ------------------------------------------------------------------

    @router.get("/dlq")
    async def dlq_list(
        subscription: str | None = Query(None, description="Filter by stream category"),
        limit: int = Query(25, ge=1, le=200, description="Page size"),
        offset: int = Query(0, ge=0, description="Number of entries to skip"),
    ) -> JSONResponse:
        """List DLQ messages across all subscriptions.

        Supports offset-based pagination via offset/limit params.
        """
        return _dlq_list(domains, subscription, limit, offset)

    @router.get("/dlq/{dlq_id}")
    async def dlq_get(dlq_id: str) -> JSONResponse:
        """Inspect a single DLQ message with full payload."""
        return _dlq_get(domains, dlq_id)

    @router.post("/dlq/{dlq_id}/replay")
    async def dlq_replay(dlq_id: str) -> JSONResponse:
        """Replay a single DLQ message back to its original stream."""
        return _dlq_replay(domains, dlq_id)

    @router.post("/dlq/replay-all")
    async def dlq_replay_all(
        subscription: str = Query(..., description="Stream category (required)"),
    ) -> JSONResponse:
        """Replay all DLQ messages for a subscription."""
        return _dlq_replay_all(domains, subscription)

    @router.delete("/dlq")
    async def dlq_purge(
        subscription: str = Query(..., description="Stream category (required)"),
    ) -> JSONResponse:
        """Purge all DLQ messages for a subscription."""
        return _dlq_purge(domains, subscription)

    @router.delete("/traces")
    async def delete_traces() -> JSONResponse:
        """Clear all persisted trace history."""
        return _delete_traces(domains)

    return router
