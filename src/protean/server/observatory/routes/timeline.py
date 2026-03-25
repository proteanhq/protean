"""Event Store Timeline API for the Protean Observatory.

Provides chronological browsing of domain events/commands from the event store
with filtering and cursor-based pagination.

Data sources:

1. **Event store ``$all`` stream** — all messages in global order.
2. **Domain registry metadata** — aggregate names and stream categories.

Endpoints:
    GET /timeline/events          — Paginated event list with filtering
    GET /timeline/events/{message_id} — Single event detail
    GET /timeline/stats           — Summary statistics
    GET /timeline/correlation/{correlation_id} — Correlation chain + causation tree
    GET /timeline/aggregate/{stream_category}/{aggregate_id} — Aggregate event history
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from protean.port.event_store import CausationNode

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Pagination defaults
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_message(raw_msg: dict[str, Any], domain_name: str) -> dict[str, Any]:
    """Convert a raw event store message dict to a JSON-safe timeline entry."""
    metadata = raw_msg.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    headers = metadata.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}
    domain_meta = metadata.get("domain", {})
    if not isinstance(domain_meta, dict):
        domain_meta = {}
    event_store_meta = metadata.get("event_store", {})
    if not isinstance(event_store_meta, dict):
        event_store_meta = {}

    return {
        "message_id": headers.get("id"),
        "type": raw_msg.get("type", headers.get("type")),
        "stream": raw_msg.get("stream_name", headers.get("stream")),
        "kind": domain_meta.get("kind"),
        "global_position": raw_msg.get(
            "global_position", event_store_meta.get("global_position")
        ),
        "position": raw_msg.get("position", event_store_meta.get("position")),
        "time": str(raw_msg["time"]) if raw_msg.get("time") else headers.get("time"),
        "correlation_id": domain_meta.get("correlation_id"),
        "causation_id": domain_meta.get("causation_id"),
        "domain": domain_name,
    }


def _serialize_message_detail(
    raw_msg: dict[str, Any], domain_name: str
) -> dict[str, Any]:
    """Convert a raw event store message dict to a full detail response."""
    summary = _serialize_message(raw_msg, domain_name)
    summary["data"] = raw_msg.get("data", {})
    summary["metadata"] = raw_msg.get("metadata", {})
    return summary


def _extract_message_id(msg: dict[str, Any]) -> str | None:
    """Extract the Protean message ID (headers.id) from a raw message dict."""
    metadata = msg.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    headers = metadata.get("headers")
    if not headers or not isinstance(headers, dict):
        return None
    return headers.get("id")


def _extract_stream_category(msg: dict[str, Any]) -> str:
    """Extract the stream category from a raw message."""
    metadata = msg.get("metadata", {})
    if isinstance(metadata, dict):
        domain_meta = metadata.get("domain", {})
        if isinstance(domain_meta, dict):
            cat = domain_meta.get("stream_category")
            if cat:
                return cat

    stream = msg.get("stream_name", "")
    if stream:
        category, _, _ = stream.partition("-")
        return category
    return ""


def _extract_kind(msg: dict[str, Any]) -> str | None:
    """Extract the kind (EVENT/COMMAND) from a raw message."""
    metadata = msg.get("metadata", {})
    if isinstance(metadata, dict):
        domain_meta = metadata.get("domain", {})
        if isinstance(domain_meta, dict):
            return domain_meta.get("kind")
    return None


def _extract_event_type(msg: dict[str, Any]) -> str | None:
    """Extract the event type from a raw message."""
    return msg.get("type")


def _extract_aggregate_id(msg: dict[str, Any]) -> str | None:
    """Extract the aggregate ID from the stream name (part after '-')."""
    stream = msg.get("stream_name", "")
    if not stream:
        metadata = msg.get("metadata", {})
        if isinstance(metadata, dict):
            headers = metadata.get("headers", {})
            if isinstance(headers, dict):
                stream = headers.get("stream", "")

    if stream and "-" in stream:
        _, _, identifier = stream.partition("-")
        return identifier
    return None


def collect_all_events(
    domains: list[Domain],
    *,
    cursor: int = 0,
    limit: int = _DEFAULT_LIMIT,
    order: str = "asc",
    stream_category: str | None = None,
    event_type: str | None = None,
    aggregate_id: str | None = None,
    kind: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Read events from all domains' event stores with filtering and pagination.

    Returns:
        Tuple of (events, next_cursor). next_cursor is None when there are
        no more results.
    """
    all_events: list[tuple[dict[str, Any], str]] = []

    for domain in domains:
        try:
            with domain.domain_context():
                store = domain.event_store.store
                raw_messages = store._read("$all", no_of_messages=1_000_000)

                for msg in raw_messages:
                    # Exclude snapshot messages from the timeline
                    stream = msg.get("stream_name", "")
                    if ":snapshot-" in stream or msg.get("type") == "SNAPSHOT":
                        continue
                    all_events.append((msg, domain.name))
        except Exception:
            logger.debug("Failed to read events from %s", domain.name, exc_info=True)

    # Sort by global_position (ascending)
    all_events.sort(key=lambda x: x[0].get("global_position", 0))

    # Apply cursor filter based on order direction
    if cursor > 0:
        if order == "desc":
            all_events = [
                (msg, dn)
                for msg, dn in all_events
                if msg.get("global_position", 0) <= cursor
            ]
        else:
            all_events = [
                (msg, dn)
                for msg, dn in all_events
                if msg.get("global_position", 0) >= cursor
            ]

    if order == "desc":
        all_events.reverse()

    # Apply content filters
    filtered: list[dict[str, Any]] = []
    for msg, domain_name in all_events:
        if stream_category and _extract_stream_category(msg) != stream_category:
            continue
        if event_type and _extract_event_type(msg) != event_type:
            continue
        if aggregate_id and _extract_aggregate_id(msg) != aggregate_id:
            continue
        if kind and _extract_kind(msg) != kind.upper():
            continue
        filtered.append(_serialize_message(msg, domain_name))

    # Apply pagination limit
    page = filtered[:limit]

    # Determine next cursor based on order direction
    next_cursor: int | None = None
    if len(filtered) > limit and page:
        last_pos = page[-1].get("global_position")
        if last_pos is not None:
            if order == "desc":
                next_cursor = last_pos - 1
            else:
                next_cursor = last_pos + 1

    return page, next_cursor


def find_event_by_id(domains: list[Domain], message_id: str) -> dict[str, Any] | None:
    """Find a single event by its message ID across all domains.

    Returns the full event detail dict, or None if not found.
    """
    for domain in domains:
        try:
            with domain.domain_context():
                store = domain.event_store.store
                raw_messages = store._read("$all", no_of_messages=1_000_000)

                for msg in raw_messages:
                    if _extract_message_id(msg) == message_id:
                        return _serialize_message_detail(msg, domain.name)
        except Exception:
            logger.debug("Failed to search events in %s", domain.name, exc_info=True)

    return None


def collect_timeline_stats(domains: list[Domain]) -> dict[str, Any]:
    """Collect summary statistics across all domains' event stores.

    Returns:
        Dict with total_events, last_event_time, active_streams,
        events_per_minute.
    """
    total_events = 0
    active_streams: set[str] = set()
    last_event_time: str | None = None
    last_event_datetime: datetime | None = None
    first_event_datetime: datetime | None = None

    for domain in domains:
        try:
            with domain.domain_context():
                store = domain.event_store.store
                raw_messages = store._read("$all", no_of_messages=1_000_000)

                for msg in raw_messages:
                    # Exclude snapshot messages from stats
                    stream = msg.get("stream_name", "")
                    if ":snapshot-" in stream or msg.get("type") == "SNAPSHOT":
                        continue

                    total_events += 1

                    if stream:
                        active_streams.add(stream)

                    raw_time = msg.get("time")
                    if raw_time:
                        if isinstance(raw_time, datetime):
                            msg_dt = raw_time
                        elif isinstance(raw_time, str):
                            try:
                                msg_dt = datetime.fromisoformat(raw_time)
                            except (ValueError, TypeError):
                                continue
                        else:
                            continue

                        if last_event_datetime is None or msg_dt > last_event_datetime:
                            last_event_datetime = msg_dt
                            last_event_time = str(raw_time)

                        if (
                            first_event_datetime is None
                            or msg_dt < first_event_datetime
                        ):
                            first_event_datetime = msg_dt
        except Exception:
            logger.debug("Failed to collect stats from %s", domain.name, exc_info=True)

    # Calculate events per minute
    events_per_minute: float | None = None
    if first_event_datetime and last_event_datetime and total_events > 1:
        # Normalize both to comparable datetimes
        first = first_event_datetime.replace(tzinfo=None)
        last = last_event_datetime.replace(tzinfo=None)
        duration = (last - first).total_seconds()
        if duration > 0:
            events_per_minute = round(total_events / (duration / 60), 2)

    return {
        "total_events": total_events,
        "last_event_time": last_event_time,
        "active_streams": len(active_streams),
        "events_per_minute": events_per_minute,
    }


# ---------------------------------------------------------------------------
# Correlation chain helpers
# ---------------------------------------------------------------------------


def _build_causation_tree_from_group(
    store: Any, group: list[dict[str, Any]]
) -> CausationNode | None:
    """Build a causation tree from a pre-loaded correlation group.

    Replicates the logic of ``BaseEventStore.build_causation_tree`` but
    operates on an already-loaded group to avoid a redundant ``$all`` scan.
    """
    if not group:
        return None

    by_id: dict[str, dict[str, Any]] = {}
    children_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roots: list[dict[str, Any]] = []

    for m in group:
        hid = store._extract_message_id(m)
        if hid:
            by_id[hid] = m
        cid = store._extract_causation_id(m)
        if cid:
            children_map[cid].append(m)
        else:
            roots.append(m)

    for cid in children_map:
        children_map[cid].sort(key=lambda m: m.get("global_position", 0))

    visited: set[str] = set()

    def _build_node(raw_msg: dict[str, Any]) -> CausationNode:
        hid = store._extract_message_id(raw_msg) or "?"
        visited.add(hid)

        metadata = raw_msg.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        headers = metadata.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}
        domain_meta = metadata.get("domain", {})
        if not isinstance(domain_meta, dict):
            domain_meta = {}

        node = CausationNode(
            message_id=hid,
            message_type=raw_msg.get("type", headers.get("type", "?")),
            kind=domain_meta.get("kind", "?"),
            stream=raw_msg.get("stream_name", headers.get("stream", "?")),
            time=str(raw_msg.get("time", "")) if raw_msg.get("time") else None,
            global_position=raw_msg.get("global_position"),
        )

        for child_msg in children_map.get(hid, []):
            child_id = store._extract_message_id(child_msg)
            if child_id and child_id not in visited:
                node.children.append(_build_node(child_msg))

        return node

    if not roots:
        root_candidates = [
            m for m in group if store._extract_causation_id(m) not in by_id
        ]
        roots = root_candidates if root_candidates else [group[0]]

    roots.sort(key=lambda m: m.get("global_position", 0))
    return _build_node(roots[0])


def build_correlation_response(
    domains: list[Domain], correlation_id: str
) -> dict[str, Any] | None:
    """Build the correlation chain response for a given correlation ID.

    Searches across all domains for the correlation group, builds the
    causation tree, and returns the serialized result.  The correlation
    group is loaded once and reused for both the flat event list and the
    causation tree to avoid redundant ``$all`` scans.

    Returns:
        Dict with correlation_id, events, tree, and event_count; or None if
        no events found.
    """
    for domain in domains:
        try:
            with domain.domain_context():
                store = domain.event_store.store
                group = store._load_correlation_group(correlation_id)
                if not group:
                    continue

                # Serialize the flat event list
                events = [_serialize_message(msg, domain.name) for msg in group]
                events.sort(key=lambda e: e.get("global_position") or 0)

                # Build the causation tree from the already-loaded group
                tree_root = _build_causation_tree_from_group(store, group)
                tree = asdict(tree_root) if tree_root else None

                return {
                    "correlation_id": correlation_id,
                    "events": events,
                    "tree": tree,
                    "event_count": len(events),
                }
        except Exception:
            logger.debug(
                "Failed to build correlation chain from %s",
                domain.name,
                exc_info=True,
            )

    return None


def collect_aggregate_history(
    domains: list[Domain],
    stream_category: str,
    aggregate_id: str,
) -> dict[str, Any] | None:
    """Collect the full event history for one aggregate instance.

    Reads the aggregate's stream and returns all events in position order
    along with current version information.

    Returns:
        Dict with stream, aggregate_id, current_version, events, and
        event_count; or None if no events found.
    """
    stream_name = f"{stream_category}-{aggregate_id}"

    for domain in domains:
        try:
            with domain.domain_context():
                store = domain.event_store.store
                raw_messages = store._read(stream_name, no_of_messages=1_000_000)
                if not raw_messages:
                    continue

                events = [_serialize_message(msg, domain.name) for msg in raw_messages]

                # Derive stream version from the last message's position
                last_msg = raw_messages[-1]
                current_version = last_msg.get("position")

                return {
                    "stream": stream_name,
                    "aggregate_id": aggregate_id,
                    "stream_category": stream_category,
                    "current_version": current_version,
                    "events": events,
                    "event_count": len(events),
                }
        except Exception:
            logger.debug(
                "Failed to read aggregate history from %s",
                domain.name,
                exc_info=True,
            )

    return None


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_timeline_router(domains: list["Domain"]) -> APIRouter:
    """Create the /timeline API router."""
    router = APIRouter()

    @router.get("/timeline/events")
    async def list_events(
        cursor: int = Query(0, ge=0, description="Global position cursor"),
        limit: int = Query(
            _DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Page size"
        ),
        order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
        stream_category: str | None = Query(
            None, description="Filter by stream category"
        ),
        event_type: str | None = Query(None, description="Filter by event type"),
        aggregate_id: str | None = Query(None, description="Filter by aggregate ID"),
        kind: str | None = Query(
            None, pattern="^(EVENT|COMMAND)$", description="Filter by kind"
        ),
    ) -> JSONResponse:
        """Paginated event list from the $all stream with filtering."""
        events, next_cursor = collect_all_events(
            domains,
            cursor=cursor,
            limit=limit,
            order=order,
            stream_category=stream_category,
            event_type=event_type,
            aggregate_id=aggregate_id,
            kind=kind,
        )

        return JSONResponse(
            content={
                "events": events,
                "next_cursor": next_cursor,
                "count": len(events),
            }
        )

    @router.get("/timeline/events/{message_id}")
    async def get_event(message_id: str) -> JSONResponse:
        """Single event detail with full payload and metadata."""
        event = find_event_by_id(domains, message_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return JSONResponse(content=event)

    @router.get("/timeline/stats")
    async def get_stats() -> JSONResponse:
        """Summary statistics for the event store timeline."""
        stats = collect_timeline_stats(domains)
        return JSONResponse(content=stats)

    @router.get("/timeline/correlation/{correlation_id}")
    async def get_correlation_chain(correlation_id: str) -> JSONResponse:
        """All events in a correlation chain with causation tree."""
        result = build_correlation_response(domains, correlation_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="No events found for correlation ID",
            )
        return JSONResponse(content=result)

    @router.get("/timeline/aggregate/{stream_category}/{aggregate_id}")
    async def get_aggregate_history(
        stream_category: str, aggregate_id: str
    ) -> JSONResponse:
        """Full event history for one aggregate instance."""
        result = collect_aggregate_history(domains, stream_category, aggregate_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="No events found for aggregate",
            )
        return JSONResponse(content=result)

    return router
