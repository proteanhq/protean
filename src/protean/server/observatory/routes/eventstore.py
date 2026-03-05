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
    GET /eventstore/streams — All aggregate streams + outbox
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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

    return router
