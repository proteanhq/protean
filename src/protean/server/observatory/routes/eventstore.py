"""Event Store monitoring API for the Protean Observatory.

Provides aggregate-level stream statistics and outbox status.

Data sources:

1. **Domain registry metadata** (always available) — aggregate names,
   stream categories, event-sourced flag.
2. **Event store stats** (degrades gracefully) — instance counts and
   head positions via ``_stream_identifiers()`` and
   ``_stream_head_position()``.
3. **Outbox status** (degrades gracefully) — pending/processing counts
   via ``count_by_status()``.

Endpoints:
    GET /eventstore/streams                     — All aggregate streams + outbox
    GET /eventstore/streams/{stream_category}   — Instances for a stream category
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_time(message: Any) -> str | None:
    """Extract a timestamp string from a message object."""
    t = getattr(message, "time", None)
    if t is not None:
        return str(t)
    metadata = getattr(message, "metadata", None)
    if metadata and hasattr(metadata, "timestamp"):
        return str(metadata.timestamp)
    return None


def _extract_message_type(message: Any) -> str | None:
    """Extract the message type string from a message object."""
    # Try type attribute first
    t = getattr(message, "type", None)
    if t is not None:
        return str(t)
    # Fall back to class name
    cls = type(message)
    if cls.__name__ != "dict":
        return cls.__name__
    return None


def collect_aggregate_stream_metadata(
    domains: list["Domain"],
) -> list[dict[str, Any]]:
    """Walk domain registries for all aggregates, extract stream metadata.

    Returns a list of aggregate dicts with keys:
        name, qualname, domain, stream_category, is_event_sourced,
        instance_count, head_position, _domain (internal ref)
    """
    aggregates: list[dict[str, Any]] = []

    for domain in domains:
        registry_dict = getattr(domain.registry, "aggregates", {})
        for _fqn, record in registry_dict.items():
            agg_cls = record.cls
            meta = getattr(agg_cls, "meta_", None)

            stream_category = getattr(meta, "stream_category", None) if meta else None
            is_event_sourced = (
                getattr(meta, "is_event_sourced", False) if meta else False
            )

            aggregates.append(
                {
                    "name": record.name,
                    "qualname": record.qualname,
                    "domain": domain.name,
                    "stream_category": stream_category,
                    "is_event_sourced": is_event_sourced,
                    "instance_count": None,
                    "head_position": None,
                    # Internal refs (stripped before serialization)
                    "_domain": domain,
                }
            )

    return aggregates


def enrich_with_event_store_stats(
    aggregates: list[dict[str, Any]],
) -> None:
    """Query event store for instance_count and head_position per aggregate.

    Modifies aggregate dicts in-place. Degrades gracefully if the event
    store is unavailable.
    """
    for agg in aggregates:
        stream_category = agg.get("stream_category")
        if not stream_category:
            continue

        domain = agg["_domain"]
        try:
            with domain.domain_context():
                store = domain.event_store.store
                identifiers = store._stream_identifiers(stream_category)
                agg["instance_count"] = len(identifiers)
        except Exception:
            logger.debug(
                "Failed to get instance count for %s",
                agg["name"],
                exc_info=True,
            )

        try:
            with domain.domain_context():
                store = domain.event_store.store
                head = store._stream_head_position(stream_category)
                agg["head_position"] = head if head >= 0 else None
        except Exception:
            logger.debug(
                "Failed to get head position for %s",
                agg["name"],
                exc_info=True,
            )


def collect_outbox_status(domains: list["Domain"]) -> dict[str, dict[str, Any]]:
    """Collect outbox counts per domain.

    Returns ``{domain_name: {"status": "ok", "counts": {...}}}``
    """
    result: dict[str, dict[str, Any]] = {}
    for domain in domains:
        try:
            with domain.domain_context():
                outbox_repo = domain._get_outbox_repo("default")
                counts = outbox_repo.count_by_status()
                result[domain.name] = {"status": "ok", "counts": counts}
        except Exception:
            logger.debug("Failed to query outbox for %s", domain.name, exc_info=True)
            result[domain.name] = {
                "status": "error",
                "error": "Failed to query outbox",
            }
    return result


def get_stream_instances(
    domain: "Domain",
    stream_category: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Enumerate instances within a stream category from the event store.

    For each instance (up to *limit*), reads events and extracts
    instance_id, event_count, first/last event timestamps, and last event type.
    """
    try:
        with domain.domain_context():
            store = domain.event_store.store
            identifiers = store._stream_identifiers(stream_category)
    except Exception:
        logger.debug(
            "Failed to enumerate instances for %s",
            stream_category,
            exc_info=True,
        )
        return []

    instances: list[dict[str, Any]] = []
    for instance_id in identifiers[:limit]:
        stream_name = f"{stream_category}-{instance_id}"
        try:
            with domain.domain_context():
                store = domain.event_store.store
                messages = store.read(stream_name)
        except Exception:
            logger.debug("Failed to read stream %s", stream_name, exc_info=True)
            continue

        if not messages:
            continue

        first_msg = messages[0]
        last_msg = messages[-1]

        instances.append(
            {
                "instance_id": instance_id,
                "event_count": len(messages),
                "first_event_time": _extract_time(first_msg),
                "last_event_time": _extract_time(last_msg),
                "last_event_type": _extract_message_type(last_msg),
            }
        )

    return instances


def _build_eventstore_summary(
    aggregates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build summary statistics from the aggregate list."""
    total_instances = 0
    total_event_sourced = 0

    for agg in aggregates:
        if agg.get("is_event_sourced"):
            total_event_sourced += 1
        count = agg.get("instance_count")
        if count is not None:
            total_instances += count

    return {
        "total_aggregates": len(aggregates),
        "total_event_sourced": total_event_sourced,
        "total_instances": total_instances,
    }


def _serialize_aggregate(agg: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of an aggregate dict (strips internal keys)."""
    return {k: v for k, v in agg.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_eventstore_router(domains: list["Domain"]) -> APIRouter:
    """Create the /eventstore API router."""
    router = APIRouter()

    @router.get("/eventstore/streams")
    async def list_streams() -> JSONResponse:
        """All aggregate streams with summary data and outbox status."""
        # 1. Collect metadata from domain registry
        aggregates = collect_aggregate_stream_metadata(domains)

        # 2. Enrich with event store stats
        try:
            enrich_with_event_store_stats(aggregates)
        except Exception:
            logger.debug("Failed to enrich event store stats", exc_info=True)

        # 3. Build summary
        summary = _build_eventstore_summary(aggregates)

        # 4. Collect outbox status
        outbox = collect_outbox_status(domains)

        return JSONResponse(
            content={
                "aggregates": [_serialize_aggregate(a) for a in aggregates],
                "summary": summary,
                "outbox": outbox,
            }
        )

    @router.get("/eventstore/streams/{stream_category:path}")
    async def stream_detail(
        stream_category: str = Path(description="Stream category name"),
        limit: int = Query(50, description="Maximum number of instances to return"),
    ) -> JSONResponse:
        """Instances for a specific aggregate stream category."""
        # Find the aggregate by stream_category
        aggregates = collect_aggregate_stream_metadata(domains)
        target = None
        for agg in aggregates:
            if agg.get("stream_category") == stream_category:
                target = agg
                break

        if target is None:
            return JSONResponse(
                content={"error": f"Stream category '{stream_category}' not found"},
                status_code=404,
            )

        # Get instances from event store
        try:
            instances = get_stream_instances(
                target["_domain"], stream_category, limit=limit
            )
        except Exception:
            logger.debug(
                "Failed to get instances for %s",
                stream_category,
                exc_info=True,
            )
            instances = []

        # Get total count and head position
        total: int | None = None
        head_position: int | None = None
        try:
            with target["_domain"].domain_context():
                store = target["_domain"].event_store.store
                identifiers = store._stream_identifiers(stream_category)
                total = len(identifiers)
                head = store._stream_head_position(stream_category)
                head_position = head if head >= 0 else None
        except Exception:
            logger.debug(
                "Failed to get stream stats for %s",
                stream_category,
                exc_info=True,
            )

        return JSONResponse(
            content={
                "stream_category": stream_category,
                "aggregate": target["name"],
                "instances": instances,
                "total": total if total is not None else len(instances),
                "head_position": head_position,
            }
        )

    return router
