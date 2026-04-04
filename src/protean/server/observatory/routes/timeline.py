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
    GET /timeline/traces/recent   — Recent correlation chains with summaries
    GET /timeline/traces/search   — Search correlation chains by criteria
"""

from __future__ import annotations

import json
import logging
import time as _time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from protean.port.event_store import CausationNode
from protean.server.tracing import TRACE_STREAM

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Pagination defaults
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _unique_store_domains(domains: list[Domain]) -> list[Domain]:
    """Return a deduplicated list of domains, one per unique event store instance.

    When multiple domains share the same event store (common in multi-bounded-context
    apps using a single database), reading ``$all`` from each would return duplicate
    messages.  This helper keeps only the first domain for each distinct store,
    comparing by connection URI rather than object identity (each domain creates
    its own store instance even when they share the same database).
    """
    seen_stores: set[str] = set()
    unique: list[Domain] = []
    for domain in domains:
        try:
            store = domain.event_store.store
            # Use the database URI as the identity key — object identity
            # doesn't work because each domain creates its own store instance.
            store_key = (
                store.conn_info.get("database_uri", "")
                if hasattr(store, "conn_info")
                else ""
            )
            if not store_key:
                store_key = str(id(store))  # Fallback for stores without conn_info
        except Exception:
            store_key = str(id(domain))  # Fallback — treat as unique
        if store_key not in seen_stores:
            seen_stores.add(store_key)
            unique.append(domain)
    return unique


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
        "time": raw_msg["time"].isoformat()
        if raw_msg.get("time") and hasattr(raw_msg["time"], "isoformat")
        else str(raw_msg["time"])
        if raw_msg.get("time")
        else headers.get("time"),
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

    for domain in _unique_store_domains(domains):
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
    for domain in _unique_store_domains(domains):
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

    for domain in _unique_store_domains(domains):
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
                            last_event_time = (
                                raw_time.isoformat()
                                if hasattr(raw_time, "isoformat")
                                else str(raw_time)
                            )

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
    store: Any,
    group: list[dict[str, Any]],
    traces_by_message_id: dict[str, dict[str, Any]] | None = None,
) -> CausationNode | None:
    """Build a causation tree from a pre-loaded correlation group.

    Replicates the logic of ``BaseEventStore.build_causation_tree`` but
    operates on an already-loaded group to avoid a redundant ``$all`` scan.

    Args:
        store: The event store instance (used for metadata extraction helpers).
        group: Pre-loaded list of raw message dicts from the event store.
        traces_by_message_id: Optional mapping of message_id to trace data
            (with ``handler``, ``duration_ms`` keys).  When provided, nodes
            are enriched with handler attribution and timing.
    """
    if not group:
        return None

    traces = traces_by_message_id or {}

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

    def _parse_time_ms(time_val: Any) -> float | None:
        """Convert a time value to epoch milliseconds for delta computation."""
        if time_val is None:
            return None
        if isinstance(time_val, datetime):
            return time_val.timestamp() * 1000
        if isinstance(time_val, str) and time_val:
            try:
                dt = datetime.fromisoformat(time_val)
                return dt.timestamp() * 1000
            except (ValueError, TypeError):
                return None
        return None

    def _build_node(
        raw_msg: dict[str, Any], parent_time_ms: float | None = None
    ) -> CausationNode:
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

        time_val = raw_msg.get("time")
        time_str: str | None
        if time_val and hasattr(time_val, "isoformat"):
            time_str = time_val.isoformat()
        elif time_val:
            time_str = str(time_val)
        else:
            time_str = None

        # Compute delta_ms from parent timestamp
        node_time_ms = (
            _parse_time_ms(time_val) if time_val else _parse_time_ms(time_str)
        )
        delta_ms: float | None = None
        if parent_time_ms is not None and node_time_ms is not None:
            delta_ms = round(node_time_ms - parent_time_ms, 2)

        # Enrich from trace data
        trace = traces.get(hid, {})

        node = CausationNode(
            message_id=hid,
            message_type=raw_msg.get("type", headers.get("type", "?")),
            kind=domain_meta.get("kind", "?"),
            stream=raw_msg.get("stream_name", headers.get("stream", "?")),
            time=time_str,
            global_position=raw_msg.get("global_position"),
            handler=trace.get("handler"),
            duration_ms=trace.get("duration_ms"),
            delta_ms=delta_ms,
        )

        for child_msg in children_map.get(hid, []):
            child_id = store._extract_message_id(child_msg)
            if child_id and child_id not in visited:
                node.children.append(_build_node(child_msg, node_time_ms))

        return node

    if not roots:
        root_candidates = [
            m for m in group if store._extract_causation_id(m) not in by_id
        ]
        roots = root_candidates if root_candidates else [group[0]]

    roots.sort(key=lambda m: m.get("global_position", 0))
    return _build_node(roots[0])


def _load_traces_for_correlation(
    domains: list[Domain], correlation_id: str
) -> dict[str, dict[str, Any]]:
    """Load trace entries from the Redis trace stream for a correlation ID.

    Returns a dict keyed by ``message_id`` with values containing
    ``handler`` and ``duration_ms`` from the most recent matching
    ``handler.completed`` or ``handler.failed`` trace entry.
    """
    traces: dict[str, dict[str, Any]] = {}

    for d in domains:
        try:
            with d.domain_context():
                broker = d.brokers.get("default")
                if broker and hasattr(broker, "redis_instance"):
                    redis_conn = broker.redis_instance
                    break
        except Exception:
            continue
    else:
        return traces

    # Read the last 24 hours of traces to bound memory usage
    now_ms = int(_time.time() * 1000)
    min_id = str(now_ms - 86_400_000)  # 24-hour window

    try:
        raw_entries = redis_conn.xrange(TRACE_STREAM, min=min_id)
    except Exception:
        logger.debug("Failed to read trace stream for enrichment", exc_info=True)
        return traces

    for _stream_id, fields in raw_entries:
        try:
            data_raw = fields.get(b"data") or fields.get("data")
            if not data_raw:
                continue
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode("utf-8")
            trace = json.loads(data_raw)

            if trace.get("correlation_id") != correlation_id:
                continue

            event_type = trace.get("event", "")
            if event_type not in ("handler.completed", "handler.failed"):
                continue

            mid = trace.get("message_id")
            if mid:
                raw_duration = trace.get("duration_ms")
                duration_ms: float | None = None
                if raw_duration is not None:
                    try:
                        duration_ms = float(raw_duration)
                    except (ValueError, TypeError):
                        duration_ms = None
                traces[mid] = {
                    "handler": trace.get("handler"),
                    "duration_ms": duration_ms,
                }
        except (
            AttributeError,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
        ):
            logger.debug(
                "Skipping malformed trace entry during correlation enrichment",
                exc_info=True,
            )
            continue

    return traces


def _sum_tree_duration(node: CausationNode) -> float:
    """Sum raw duration_ms values across all nodes in a causation tree."""
    total = node.duration_ms or 0.0
    for child in node.children:
        total += _sum_tree_duration(child)
    return total


def build_correlation_response(
    domains: list[Domain], correlation_id: str
) -> dict[str, Any] | None:
    """Build the correlation chain response for a given correlation ID.

    Searches across all domains for the correlation group, builds the
    causation tree, and returns the serialized result.  The correlation
    group is loaded once and reused for both the flat event list and the
    causation tree to avoid redundant ``$all`` scans.

    When Redis trace data is available, nodes are enriched with handler
    attribution, processing duration, and inter-message latency.  The
    response includes ``total_duration_ms`` — the sum of all handler
    durations in the tree.

    Returns:
        Dict with correlation_id, events, tree, total_duration_ms, and
        event_count; or None if no events found.
    """
    for domain in _unique_store_domains(domains):
        try:
            with domain.domain_context():
                store = domain.event_store.store
                group = store._load_correlation_group(correlation_id)
                if not group:
                    continue

                # Serialize the flat event list
                events = [_serialize_message(msg, domain.name) for msg in group]
                events.sort(key=lambda e: e.get("global_position") or 0)

                # Load trace data for enrichment (graceful fallback)
                traces = _load_traces_for_correlation(domains, correlation_id)

                # Build the causation tree from the already-loaded group
                tree_root = _build_causation_tree_from_group(
                    store, group, traces_by_message_id=traces
                )
                tree = asdict(tree_root) if tree_root else None

                total_duration_ms: float | None = None
                if tree_root:
                    total = _sum_tree_duration(tree_root)
                    total_duration_ms = round(total, 2) if total > 0 else None

                return {
                    "correlation_id": correlation_id,
                    "events": events,
                    "tree": tree,
                    "total_duration_ms": total_duration_ms,
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

    for domain in _unique_store_domains(domains):
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
# Trace summary helpers
# ---------------------------------------------------------------------------


def _extract_correlation_id(msg: dict[str, Any]) -> str | None:
    """Extract correlation_id from a raw message dict."""
    metadata = msg.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    domain_meta = metadata.get("domain")
    if not domain_meta or not isinstance(domain_meta, dict):
        return None
    return domain_meta.get("correlation_id")


def _group_by_correlation(
    domains: list[Domain],
) -> dict[str, list[tuple[dict[str, Any], str]]]:
    """Read all events from the event store and group by correlation_id.

    Returns a dict mapping each correlation_id to its list of
    ``(raw_msg, domain_name)`` tuples, sorted by global_position within
    each group.  Messages without a correlation_id are excluded.
    """
    groups: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)

    for domain in _unique_store_domains(domains):
        try:
            with domain.domain_context():
                store = domain.event_store.store
                raw_messages = store._read("$all", no_of_messages=1_000_000)

                for msg in raw_messages:
                    stream = msg.get("stream_name", "")
                    if ":snapshot-" in stream or msg.get("type") == "SNAPSHOT":
                        continue
                    cid = _extract_correlation_id(msg)
                    if cid:
                        groups[cid].append((msg, domain.name))
        except Exception:
            logger.debug(
                "Failed to read events from %s for grouping",
                domain.name,
                exc_info=True,
            )

    # Sort each group by global_position
    for cid in groups:
        groups[cid].sort(key=lambda x: x[0].get("global_position", 0))

    return groups


def _build_trace_summary(
    correlation_id: str,
    group: list[tuple[dict[str, Any], str]],
) -> dict[str, Any]:
    """Build a trace summary dict from a correlation group.

    Returns a summary with correlation_id, root_type, event_count,
    started_at, and unique streams.
    """
    root_msg = group[0][0]
    metadata = root_msg.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    headers = metadata.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}
    root_type = root_msg.get("type", headers.get("type", "?"))

    # Extract started_at from the earliest message, with headers fallback
    time_val = root_msg.get("time")
    started_at: str | None
    if time_val and hasattr(time_val, "isoformat"):
        started_at = time_val.isoformat()
    elif time_val:
        started_at = str(time_val)
    else:
        started_at = headers.get("time")

    # Collect unique streams
    streams: list[str] = []
    seen_streams: set[str] = set()
    for msg, _ in group:
        stream = msg.get("stream_name", "")
        if stream and stream not in seen_streams:
            seen_streams.add(stream)
            streams.append(stream)

    return {
        "correlation_id": correlation_id,
        "root_type": root_type,
        "event_count": len(group),
        "started_at": started_at,
        "streams": streams,
        "_root_global_position": root_msg.get("global_position", 0),
    }


def collect_recent_traces(
    domains: list[Domain],
    *,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Return the most recent correlation chains as trace summaries.

    Chains are sorted by the timestamp of their first (root) message,
    most recent first.  Each summary contains correlation_id, root_type,
    event_count, started_at, and streams.
    """
    groups = _group_by_correlation(domains)

    summaries = [_build_trace_summary(cid, grp) for cid, grp in groups.items() if grp]

    # Sort by root global_position descending (most recent first)
    summaries.sort(key=lambda s: s.get("_root_global_position", 0), reverse=True)

    result = summaries[:limit]
    for s in result:
        s.pop("_root_global_position", None)
    return result


def search_traces(
    domains: list[Domain],
    *,
    aggregate_id: str | None = None,
    event_type: str | None = None,
    command_type: str | None = None,
    stream_category: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Search correlation chains by criteria.

    At least one search parameter must be provided.  A chain matches if
    **any** message in its group matches the filter.

    Args:
        aggregate_id: Match chains containing a message for this aggregate ID.
        event_type: Match chains containing a message of this type.
        command_type: Alias for event_type — match chains containing a
            command of this type.
        stream_category: Match chains containing a message in this stream
            category.
        limit: Maximum number of results to return.

    Returns:
        List of trace summaries matching the criteria, sorted by
        root global_position descending.

    Raises:
        ValueError: If no search parameter is provided.
    """
    if not any((aggregate_id, event_type, command_type, stream_category)):
        raise ValueError(
            "At least one search parameter must be provided: "
            "aggregate_id, event_type, command_type, or stream_category"
        )

    groups = _group_by_correlation(domains)

    matching: list[dict[str, Any]] = []

    for cid, grp in groups.items():
        if not grp:
            continue

        match = False
        for msg, _ in grp:
            if aggregate_id and _extract_aggregate_id(msg) == aggregate_id:
                match = True
                break
            if event_type and _extract_event_type(msg) == event_type:
                match = True
                break
            if (
                command_type
                and _extract_event_type(msg) == command_type
                and _extract_kind(msg) == "COMMAND"
            ):
                match = True
                break
            if stream_category and _extract_stream_category(msg) == stream_category:
                match = True
                break

        if match:
            matching.append(_build_trace_summary(cid, grp))

    matching.sort(key=lambda s: s.get("_root_global_position", 0), reverse=True)
    result = matching[:limit]
    for s in result:
        s.pop("_root_global_position", None)
    return result


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

    @router.get("/timeline/traces/recent")
    async def list_recent_traces(
        limit: int = Query(
            _DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max traces to return"
        ),
    ) -> JSONResponse:
        """Recent correlation chains with summary statistics."""
        traces = collect_recent_traces(domains, limit=limit)
        return JSONResponse(content={"traces": traces, "count": len(traces)})

    @router.get("/timeline/traces/search")
    async def search_traces_endpoint(
        aggregate_id: str | None = Query(None, description="Filter by aggregate ID"),
        event_type: str | None = Query(None, description="Filter by event type"),
        command_type: str | None = Query(None, description="Filter by command type"),
        stream_category: str | None = Query(
            None, description="Filter by stream category"
        ),
        limit: int = Query(
            _DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max traces to return"
        ),
    ) -> JSONResponse:
        """Search correlation chains by aggregate ID, event type, or stream."""
        if not any([aggregate_id, event_type, command_type, stream_category]):
            raise HTTPException(
                status_code=400,
                detail="At least one search parameter is required",
            )

        traces = search_traces(
            domains,
            aggregate_id=aggregate_id,
            event_type=event_type,
            command_type=command_type,
            stream_category=stream_category,
            limit=limit,
        )
        return JSONResponse(content={"traces": traces, "count": len(traces)})

    return router
