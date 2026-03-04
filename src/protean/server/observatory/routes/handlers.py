"""Handler metrics API for the Protean Observatory.

Provides aggregated handler data by merging three sources:
1. Domain registry metadata (always available, no Redis)
2. Subscription status (degrades gracefully)
3. Trace metrics from Redis Stream (requires Redis)

Endpoints:
    GET /handlers           — All handlers with metrics and subscription status
    GET /handlers/{name}    — Single handler detail with recent messages
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

# Window string → milliseconds mapping (same as api.py)
_WINDOW_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
}

# Error event types
_ERROR_EVENTS = {"handler.failed", "message.dlq"}

# Throughput sparkline bucket size
_THROUGHPUT_BUCKET_S = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _decode_stream_id(stream_id: bytes | str) -> str:
    """Decode a Redis stream ID that may be bytes or str."""
    if isinstance(stream_id, bytes):
        return stream_id.decode("utf-8")
    return str(stream_id)


def _extract_handled_messages(handler_cls: type) -> list[str]:
    """Extract handled message type names from a handler class.

    Reads ``_handlers`` dict (a defaultdict(set) mapping __type__ strings
    to sets of handler methods). Skips the ``$any`` catch-all key.
    Returns short class names extracted from __type__ strings
    (e.g. ``"MyApp.OrderPlaced.v1"`` → ``"OrderPlaced"``).
    """
    handlers_dict = getattr(handler_cls, "_handlers", None)
    if not handlers_dict:
        return []

    names: list[str] = []
    for type_key in sorted(handlers_dict.keys()):
        if type_key == "$any":
            continue
        # __type__ format: "App.ClassName.v1" — extract the class name part
        parts = type_key.rsplit(".", 2)
        if len(parts) >= 2:
            names.append(parts[-2])  # e.g. "OrderPlaced" from "App.OrderPlaced.v1"
        else:
            names.append(type_key)
    return names


def _handler_type_label(class_type_value: str) -> str:
    """Map DomainObjects enum value to a display label."""
    mapping = {
        "EVENT_HANDLER": "event_handler",
        "COMMAND_HANDLER": "command_handler",
        "PROJECTOR": "projector",
        "SUBSCRIBER": "subscriber",
        "PROCESS_MANAGER": "process_manager",
    }
    return mapping.get(class_type_value, class_type_value.lower())


def _infer_aggregate(handler_cls: type) -> str | None:
    """Infer the aggregate name from a handler's meta_.part_of."""
    meta = getattr(handler_cls, "meta_", None)
    if meta is None:
        return None

    # Projectors use projector_for
    projector_for = getattr(meta, "projector_for", None)
    if projector_for:
        return projector_for.__name__

    # Event/command handlers use part_of
    part_of = getattr(meta, "part_of", None)
    if part_of:
        return part_of.__name__

    return None


def _infer_stream_categories(handler_cls: type, class_type: str) -> list[str]:
    """Infer stream categories for a handler."""
    meta = getattr(handler_cls, "meta_", None)
    if meta is None:
        return []

    # Projectors and process managers have stream_categories list
    if class_type in ("PROJECTOR", "PROCESS_MANAGER"):
        cats = getattr(meta, "stream_categories", None)
        if cats:
            return list(cats)

    # Event/command handlers use stream_category (singular)
    cat = getattr(meta, "stream_category", None)
    if cat:
        return [cat]

    return []


def collect_handler_metadata(domains: list[Domain]) -> list[dict[str, Any]]:
    """Walk domain registries, extract per-handler metadata (no Redis needed).

    Returns a list of handler dicts with keys:
        name, qualname, type, domain, aggregate, stream_categories,
        handled_messages
    """
    handlers: list[dict[str, Any]] = []

    registry_attrs = [
        ("event_handlers", "EVENT_HANDLER"),
        ("command_handlers", "COMMAND_HANDLER"),
        ("projectors", "PROJECTOR"),
        ("subscribers", "SUBSCRIBER"),
    ]

    for domain in domains:
        domain_name = domain.name
        for attr, class_type in registry_attrs:
            registry_dict = getattr(domain.registry, attr, {})
            for _name, record in registry_dict.items():
                handler_cls = record.cls
                handler_type = _handler_type_label(class_type)

                # Handled messages
                if class_type == "SUBSCRIBER":
                    # Subscribers use __call__, no _handlers dict
                    stream = getattr(handler_cls.meta_, "stream", None)
                    handled = [stream] if stream else []
                else:
                    handled = _extract_handled_messages(handler_cls)

                # Stream categories
                if class_type == "SUBSCRIBER":
                    stream = getattr(handler_cls.meta_, "stream", None)
                    stream_cats = [stream] if stream else []
                else:
                    stream_cats = _infer_stream_categories(handler_cls, class_type)

                handlers.append(
                    {
                        "name": record.name,
                        "qualname": record.qualname,
                        "type": handler_type,
                        "domain": domain_name,
                        "aggregate": _infer_aggregate(handler_cls),
                        "stream_categories": stream_cats,
                        "handled_messages": handled,
                        "subscription": None,
                        "metrics": None,
                    }
                )

    return handlers


def merge_subscription_status(
    handlers: list[dict[str, Any]],
    domains: list[Domain],
) -> None:
    """Merge subscription status into handler dicts in-place.

    Builds a lookup from handler_name → SubscriptionStatus(es), then
    merges into the corresponding handler dict.

    For projectors listening to multiple streams: aggregates lag/pending/dlq
    across their subscriptions.
    For command handlers: all handlers sharing a stream get the shared
    CommandDispatcher subscription status.
    """
    # Collect all subscription statuses across domains
    all_statuses = []
    for domain in domains:
        try:
            statuses = collect_subscription_statuses(domain)
            all_statuses.extend(statuses)
        except Exception:
            logger.debug("Failed to collect subscription statuses for %s", domain.name)
            continue

    # Build lookup: handler_name → list of SubscriptionStatus
    status_by_handler: dict[str, list] = defaultdict(list)

    # Also build command stream lookup: stream_category → SubscriptionStatus
    command_stream_status: dict[str, Any] = {}

    for s in all_statuses:
        # Command dispatcher subscriptions have name like "commands:{stream}"
        if s.name.startswith("commands:"):
            stream_cat = s.name.split(":", 1)[1]
            command_stream_status[stream_cat] = s
        else:
            status_by_handler[s.handler_name].append(s)

    for h in handlers:
        name = h["name"]
        handler_type = h["type"]

        if handler_type == "command_handler":
            # Command handlers share a dispatcher subscription by stream
            for cat in h.get("stream_categories", []):
                if cat in command_stream_status:
                    s = command_stream_status[cat]
                    h["subscription"] = {
                        "status": s.status,
                        "lag": s.lag,
                        "pending": s.pending,
                        "dlq_depth": s.dlq_depth,
                        "consumer_count": s.consumer_count,
                        "subscription_type": s.subscription_type,
                    }
                    break
        elif handler_type in ("projector", "process_manager"):
            # Aggregate across multiple stream subscriptions
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

                h["subscription"] = {
                    "status": worst_status,
                    "lag": total_lag,
                    "pending": total_pending,
                    "dlq_depth": total_dlq,
                    "consumer_count": total_consumers,
                    "subscription_type": sub_type,
                }
        else:
            # Event handlers, subscribers — direct 1:1 match
            statuses = status_by_handler.get(name, [])
            if statuses:
                s = statuses[0]
                h["subscription"] = {
                    "status": s.status,
                    "lag": s.lag,
                    "pending": s.pending,
                    "dlq_depth": s.dlq_depth,
                    "consumer_count": s.consumer_count,
                    "subscription_type": s.subscription_type,
                }


def collect_per_handler_trace_metrics(
    redis_conn: Any,
    window_ms: int,
) -> dict[str, dict[str, Any]]:
    """Single XRANGE pass over trace stream, group by handler field.

    Returns:
        {handler_name: {processed, failed, error_rate, avg_latency_ms,
                        throughput: list[int]}}
    """
    if redis_conn is None:
        return {}

    now_ms = int(time.time() * 1000)
    min_id = str(now_ms - window_ms)
    bucket_ms = _THROUGHPUT_BUCKET_S * 1000
    bucket_count = max(1, window_ms // bucket_ms)
    # Cap buckets for large windows to keep response reasonable
    if bucket_count > 120:
        bucket_count = 120

    try:
        raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
    except Exception as e:
        logger.debug("Error reading trace stream for handler metrics: %s", e)
        return {}

    # Accumulate per-handler stats
    stats: dict[str, dict[str, Any]] = {}

    for stream_id, fields in raw_entries:
        try:
            data_raw = fields.get(b"data") or fields.get("data")
            if not data_raw:
                continue
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode("utf-8")
            trace = json.loads(data_raw)

            handler_name = trace.get("handler")
            if not handler_name:
                continue

            event_type = trace.get("event", "")

            if handler_name not in stats:
                stats[handler_name] = {
                    "processed": 0,
                    "failed": 0,
                    "latency_sum": 0.0,
                    "latency_count": 0,
                    "throughput": [0] * bucket_count,
                }

            entry = stats[handler_name]

            if event_type == "handler.completed":
                entry["processed"] += 1
                duration = trace.get("duration_ms")
                if duration is not None:
                    entry["latency_sum"] += float(duration)
                    entry["latency_count"] += 1

                # Bucket into throughput sparkline
                sid = _decode_stream_id(stream_id)
                ts_ms = int(sid.split("-")[0])
                bucket_idx = (ts_ms - (now_ms - window_ms)) // bucket_ms
                if 0 <= bucket_idx < bucket_count:
                    entry["throughput"][int(bucket_idx)] += 1

            elif event_type in _ERROR_EVENTS:
                entry["failed"] += 1

        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    # Compute derived metrics
    result: dict[str, dict[str, Any]] = {}
    for handler_name, entry in stats.items():
        processed = entry["processed"]
        failed = entry["failed"]
        total = processed + failed
        error_rate = round((failed / total * 100), 2) if total > 0 else 0.0
        avg_latency = (
            round(entry["latency_sum"] / entry["latency_count"], 2)
            if entry["latency_count"] > 0
            else 0.0
        )

        result[handler_name] = {
            "processed": processed,
            "failed": failed,
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency,
            "throughput": entry["throughput"],
        }

    return result


def collect_recent_messages(
    redis_conn: Any,
    handler_name: str,
    count: int = 20,
) -> list[dict[str, Any]]:
    """XREVRANGE over trace stream, filter by handler, return recent traces."""
    if redis_conn is None:
        return []

    try:
        raw_entries = redis_conn.xrevrange(TRACE_STREAM, count=count * 5)
    except Exception as e:
        logger.debug("Error reading trace stream for recent messages: %s", e)
        return []

    messages: list[dict[str, Any]] = []
    for stream_id, fields in raw_entries:
        if len(messages) >= count:
            break
        try:
            data_raw = fields.get(b"data") or fields.get("data")
            if not data_raw:
                continue
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode("utf-8")
            trace = json.loads(data_raw)

            if trace.get("handler") != handler_name:
                continue

            trace["_stream_id"] = _decode_stream_id(stream_id)
            messages.append(trace)
        except (json.JSONDecodeError, TypeError):
            continue

    return messages


def _build_summary(handlers: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary statistics from the handler list."""
    by_type: dict[str, int] = defaultdict(int)
    healthy = 0
    lagging = 0
    unknown = 0
    total_processed = 0
    total_errors = 0

    for h in handlers:
        by_type[h["type"]] += 1

        sub = h.get("subscription")
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

        metrics = h.get("metrics")
        if metrics:
            total_processed += metrics.get("processed", 0)
            total_errors += metrics.get("failed", 0)

    total = total_processed + total_errors
    error_rate = round((total_errors / total * 100), 2) if total > 0 else 0.0

    return {
        "total": len(handlers),
        "by_type": dict(by_type),
        "healthy": healthy,
        "lagging": lagging,
        "unknown": unknown,
        "total_processed": total_processed,
        "total_errors": total_errors,
        "error_rate": error_rate,
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_handlers_router(domains: list[Domain]) -> APIRouter:
    """Create the /handlers API router."""
    router = APIRouter()

    @router.get("/handlers")
    async def list_handlers(
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
    ) -> JSONResponse:
        """All handlers with aggregated metrics and subscription status."""
        window_ms = _WINDOW_MS.get(window)
        if window_ms is None:
            valid = ", ".join(_WINDOW_MS.keys())
            return JSONResponse(
                content={"error": f"Invalid window: {window}. Use {valid}."},
                status_code=400,
            )

        # 1. Collect metadata from domain registry (always works)
        handlers = collect_handler_metadata(domains)

        # 2. Merge subscription status (degrades gracefully)
        try:
            merge_subscription_status(handlers, domains)
        except Exception:
            logger.debug("Failed to merge subscription status", exc_info=True)

        # 3. Merge trace metrics (requires Redis)
        redis_conn = _get_redis(domains)
        if redis_conn:
            try:
                trace_metrics = collect_per_handler_trace_metrics(redis_conn, window_ms)
                for h in handlers:
                    h["metrics"] = trace_metrics.get(h["name"])
            except Exception:
                logger.debug("Failed to collect trace metrics", exc_info=True)

        # 4. Build summary
        summary = _build_summary(handlers)

        return JSONResponse(
            content={
                "handlers": handlers,
                "summary": summary,
                "window": window,
            }
        )

    @router.get("/handlers/{name}")
    async def handler_detail(
        name: str = Path(description="Handler class name"),
        window: str = Query("5m", description="Time window: 5m, 15m, 1h, 24h, or 7d"),
        message_count: int = Query(20, description="Number of recent messages"),
    ) -> JSONResponse:
        """Single handler detail with recent messages."""
        window_ms = _WINDOW_MS.get(window)
        if window_ms is None:
            valid = ", ".join(_WINDOW_MS.keys())
            return JSONResponse(
                content={"error": f"Invalid window: {window}. Use {valid}."},
                status_code=400,
            )

        # Find the handler by name
        handlers = collect_handler_metadata(domains)
        handler = None
        for h in handlers:
            if h["name"] == name:
                handler = h
                break

        if handler is None:
            return JSONResponse(
                content={"error": f"Handler '{name}' not found"},
                status_code=404,
            )

        # Merge subscription status
        try:
            merge_subscription_status([handler], domains)
        except Exception:
            logger.debug("Failed to merge subscription status", exc_info=True)

        # Merge trace metrics + recent messages
        redis_conn = _get_redis(domains)
        if redis_conn:
            try:
                trace_metrics = collect_per_handler_trace_metrics(redis_conn, window_ms)
                handler["metrics"] = trace_metrics.get(name)
            except Exception:
                logger.debug("Failed to collect trace metrics", exc_info=True)

            try:
                handler["recent_messages"] = collect_recent_messages(
                    redis_conn, name, count=message_count
                )
            except Exception:
                logger.debug("Failed to collect recent messages", exc_info=True)
                handler["recent_messages"] = []
        else:
            handler["recent_messages"] = []

        return JSONResponse(
            content={
                "handler": handler,
                "window": window,
            }
        )

    return router
