"""Process Manager monitoring API for the Protean Observatory.

Provides PM-level summary data by merging three sources:

1. **Domain registry metadata** (always available) — PM names, types,
   stream categories, handled messages.
2. **Subscription status** (degrades gracefully) — lag, pending, DLQ depth
   via ``collect_subscription_statuses()``.
3. **Trace metrics** (requires Redis) — per-PM processed/failed counts,
   error rate, avg latency from ``TRACE_STREAM``.

Instance-level data is fetched from the event store by reading
transition-event streams.

Endpoints:
    GET /processes                      — All PM types with summary data
    GET /processes/{name}/instances     — Instances for a specific PM type
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, List

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from protean.server.subscription_status import collect_subscription_statuses
from protean.server.tracing import TRACE_STREAM

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Window string → milliseconds mapping (same as handlers.py)
_WINDOW_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
}

# Error event types
_ERROR_EVENTS = {"handler.failed", "message.dlq"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_redis(domains: List["Domain"]) -> Any:
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


def _decode_stream_id(stream_id: bytes | str) -> str:
    """Decode a Redis stream ID that may be bytes or str."""
    if isinstance(stream_id, bytes):
        return stream_id.decode("utf-8")
    return str(stream_id)


def _extract_handled_messages(handler_cls: type) -> list[str]:
    """Extract handled message type names from a PM class.

    Reads ``_handlers`` dict, skips ``$any``, returns short class names.
    """
    handlers_dict = getattr(handler_cls, "_handlers", None)
    if not handlers_dict:
        return []

    names: list[str] = []
    for type_key in sorted(handlers_dict.keys()):
        if type_key == "$any":
            continue
        parts = type_key.rsplit(".", 2)
        if len(parts) >= 2:
            names.append(parts[-2])
        else:
            names.append(type_key)
    return names


def collect_pm_metadata(domains: list["Domain"]) -> list[dict[str, Any]]:
    """Walk domain registries, extract per-PM metadata (no Redis needed).

    Returns a list of PM dicts with keys:
        name, qualname, type, domain, stream_category, stream_categories,
        handled_messages, subscription, metrics
    """
    pms: list[dict[str, Any]] = []

    for domain in domains:
        registry_dict = getattr(domain.registry, "process_managers", {})
        for _name, record in registry_dict.items():
            pm_cls = record.cls
            meta = getattr(pm_cls, "meta_", None)

            stream_category = getattr(meta, "stream_category", None) if meta else None
            stream_cats = list(getattr(meta, "stream_categories", []) if meta else [])

            pms.append(
                {
                    "name": record.name,
                    "qualname": record.qualname,
                    "type": "process_manager",
                    "domain": domain.name,
                    "stream_category": stream_category,
                    "stream_categories": stream_cats,
                    "handled_messages": _extract_handled_messages(pm_cls),
                    "instance_count": None,
                    "subscription": None,
                    "metrics": None,
                    # Keep cls reference for instance lookup (not serialized)
                    "_cls": pm_cls,
                    "_domain": domain,
                }
            )

    return pms


def merge_pm_subscription_status(
    pms: list[dict[str, Any]],
    domains: list["Domain"],
) -> None:
    """Merge subscription status into PM dicts in-place.

    Aggregates lag/pending/dlq across multiple stream subscriptions
    per PM (same pattern as handlers.py for projectors).
    """
    all_statuses = []
    for domain in domains:
        try:
            statuses = collect_subscription_statuses(domain)
            all_statuses.extend(statuses)
        except Exception:
            logger.debug("Failed to collect subscription statuses for %s", domain.name)
            continue

    status_by_handler: dict[str, list[Any]] = defaultdict(list)
    for s in all_statuses:
        status_by_handler[s.handler_name].append(s)

    for pm in pms:
        name = pm["name"]
        statuses = status_by_handler.get(name, [])
        if statuses:
            total_lag = 0
            total_pending = 0
            total_dlq = 0
            total_consumers = 0
            worst_status = "ok"
            sub_type = statuses[0].subscription_type

            for s in statuses:
                if s.lag is not None:
                    total_lag += s.lag
                total_pending += s.pending
                total_dlq += s.dlq_depth
                total_consumers = max(total_consumers, s.consumer_count)

                if s.status == "unknown":
                    worst_status = "unknown"
                elif s.status == "lagging" and worst_status != "unknown":
                    worst_status = "lagging"

            pm["subscription"] = {
                "status": worst_status,
                "lag": total_lag,
                "pending": total_pending,
                "dlq_depth": total_dlq,
                "consumer_count": total_consumers,
                "subscription_type": sub_type,
            }


def collect_pm_trace_metrics(
    redis_conn: Any,
    pm_names: set[str],
    window_ms: int,
) -> dict[str, dict[str, Any]]:
    """Single XRANGE pass over trace stream, filter by PM handler names.

    Returns:
        ``{pm_name: {processed, failed, error_rate, avg_latency_ms}}``
    """
    if redis_conn is None or not pm_names:
        return {}

    now_ms = int(time.time() * 1000)
    min_id = str(now_ms - window_ms)

    try:
        raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
    except Exception as e:
        logger.debug("Error reading trace stream for PM metrics: %s", e)
        return {}

    stats: dict[str, dict[str, Any]] = {}

    for _stream_id, fields in raw_entries:
        try:
            data_raw = fields.get(b"data") or fields.get("data")
            if not data_raw:
                continue
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode("utf-8")
            trace = json.loads(data_raw)

            handler_name = trace.get("handler")
            if not handler_name or handler_name not in pm_names:
                continue

            event_type = trace.get("event", "")

            if handler_name not in stats:
                stats[handler_name] = {
                    "processed": 0,
                    "failed": 0,
                    "latency_sum": 0.0,
                    "latency_count": 0,
                }

            entry = stats[handler_name]

            if event_type == "handler.completed":
                entry["processed"] += 1
                duration = trace.get("duration_ms")
                if duration is not None:
                    entry["latency_sum"] += float(duration)
                    entry["latency_count"] += 1

            elif event_type in _ERROR_EVENTS:
                entry["failed"] += 1

        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    # Compute derived metrics
    result: dict[str, dict[str, Any]] = {}
    for pm_name, entry in stats.items():
        processed = entry["processed"]
        failed = entry["failed"]
        total = processed + failed
        error_rate = round((failed / total * 100), 2) if total > 0 else 0.0
        avg_latency = (
            round(entry["latency_sum"] / entry["latency_count"], 2)
            if entry["latency_count"] > 0
            else 0.0
        )

        result[pm_name] = {
            "processed": processed,
            "failed": failed,
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency,
        }

    return result


def get_pm_instance_count(domain: "Domain", pm_cls: type) -> int | None:
    """Get the number of PM instances from the event store.

    Returns ``None`` if the event store is unavailable.
    """
    meta = getattr(pm_cls, "meta_", None)
    if meta is None:
        return None

    stream_category = getattr(meta, "stream_category", None)
    if not stream_category:
        return None

    try:
        with domain.domain_context():
            store = domain.event_store.store
            identifiers = store._stream_identifiers(stream_category)
            return len(identifiers)
    except Exception:
        logger.debug(
            "Failed to get instance count for %s", pm_cls.__name__, exc_info=True
        )
        return None


def get_pm_instances(
    domain: "Domain", pm_cls: type, limit: int = 50
) -> list[dict[str, Any]]:
    """Enumerate PM instances from the event store.

    For each instance (up to *limit*), reads transition events and extracts
    current state, version, completion status, and timing info.
    """
    meta = getattr(pm_cls, "meta_", None)
    if meta is None:
        return []

    stream_category = getattr(meta, "stream_category", None)
    if not stream_category:
        return []

    try:
        with domain.domain_context():
            store = domain.event_store.store
            identifiers = store._stream_identifiers(stream_category)
    except Exception:
        logger.debug(
            "Failed to enumerate instances for %s",
            pm_cls.__name__,
            exc_info=True,
        )
        return []

    instances: list[dict[str, Any]] = []
    for instance_id in identifiers[:limit]:
        stream_name = f"{stream_category}-{instance_id}"
        try:
            with domain.domain_context():
                messages = store.read(stream_name)
        except Exception:
            logger.debug("Failed to read stream %s", stream_name, exc_info=True)
            continue

        if not messages:
            continue

        # Extract state from the last transition event
        last_msg = messages[-1]
        first_msg = messages[0]

        # Transition events store state in data
        last_data = getattr(last_msg, "data", {}) or {}
        state = last_data.get("state", {})
        is_complete = last_data.get("is_complete", False)

        # Timing from message metadata
        first_time = _extract_time(first_msg)
        last_time = _extract_time(last_msg)

        instances.append(
            {
                "instance_id": instance_id,
                "version": len(messages),
                "is_complete": is_complete,
                "state": state,
                "started_at": first_time,
                "last_activity": last_time,
                "event_count": len(messages),
            }
        )

    return instances


def _extract_time(message: Any) -> str | None:
    """Extract a timestamp string from a message object."""
    # Try message.time first (set by event store)
    t = getattr(message, "time", None)
    if t is not None:
        return str(t)
    # Fall back to metadata
    metadata = getattr(message, "metadata", None)
    if metadata and hasattr(metadata, "timestamp"):
        return str(metadata.timestamp)
    return None


def _build_summary(pms: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary statistics from the PM list."""
    healthy = 0
    lagging = 0
    unknown = 0
    total_instances = 0
    total_processed = 0
    total_errors = 0

    for pm in pms:
        sub = pm.get("subscription")
        if sub:
            status = sub.get("status", "unknown")
            if status == "ok":
                healthy += 1
            elif status == "lagging":
                lagging += 1
            else:
                unknown += 1
        else:
            unknown += 1

        count = pm.get("instance_count")
        if count is not None:
            total_instances += count

        metrics = pm.get("metrics")
        if metrics:
            total_processed += metrics.get("processed", 0)
            total_errors += metrics.get("failed", 0)

    return {
        "total": len(pms),
        "total_instances": total_instances,
        "healthy": healthy,
        "lagging": lagging,
        "unknown": unknown,
        "total_processed": total_processed,
        "total_errors": total_errors,
    }


def _serialize_pm(pm: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of a PM dict (strips internal keys)."""
    return {k: v for k, v in pm.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_processes_router(domains: list["Domain"]) -> APIRouter:
    """Create the /processes API router."""
    router = APIRouter()

    @router.get("/processes")
    async def list_processes(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
    ) -> JSONResponse:
        """All PM types with summary data."""
        window_ms = _WINDOW_MS.get(window)
        if window_ms is None:
            valid = ", ".join(_WINDOW_MS.keys())
            return JSONResponse(
                content={"error": f"Invalid window: {window}. Use {valid}."},
                status_code=400,
            )

        # 1. Collect metadata from domain registry
        pms = collect_pm_metadata(domains)

        # 2. Merge subscription status
        try:
            merge_pm_subscription_status(pms, domains)
        except Exception:
            logger.debug("Failed to merge PM subscription status", exc_info=True)

        # 3. Merge trace metrics
        redis_conn = _get_redis(domains)
        if redis_conn:
            pm_names = {pm["name"] for pm in pms}
            try:
                trace_metrics = collect_pm_trace_metrics(
                    redis_conn, pm_names, window_ms
                )
                for pm in pms:
                    pm["metrics"] = trace_metrics.get(pm["name"])
            except Exception:
                logger.debug("Failed to collect PM trace metrics", exc_info=True)

        # 4. Get instance counts
        for pm in pms:
            try:
                pm["instance_count"] = get_pm_instance_count(pm["_domain"], pm["_cls"])
            except Exception:
                logger.debug(
                    "Failed to get instance count for %s", pm["name"], exc_info=True
                )

        # 5. Build summary
        summary = _build_summary(pms)

        return JSONResponse(
            content={
                "processes": [_serialize_pm(pm) for pm in pms],
                "summary": summary,
                "window": window,
            }
        )

    @router.get("/processes/{name}/instances")
    async def process_instances(
        name: str = Path(description="Process Manager class name"),
        limit: int = Query(50, description="Maximum number of instances to return"),
    ) -> JSONResponse:
        """Instances for a specific PM type."""
        # Find the PM by name
        pms = collect_pm_metadata(domains)
        target = None
        for pm in pms:
            if pm["name"] == name:
                target = pm
                break

        if target is None:
            return JSONResponse(
                content={"error": f"Process manager '{name}' not found"},
                status_code=404,
            )

        # Get instances from event store
        try:
            instances = get_pm_instances(target["_domain"], target["_cls"], limit=limit)
        except Exception:
            logger.debug("Failed to get instances for %s", name, exc_info=True)
            instances = []

        # Get total count
        total = get_pm_instance_count(target["_domain"], target["_cls"])

        return JSONResponse(
            content={
                "process": name,
                "instances": instances,
                "total": total if total is not None else len(instances),
            }
        )

    return router
