"""Domain visualization API for the Protean Observatory.

Transforms the domain's IR into a D3-ready graph structure with
aggregate nodes, cross-aggregate edges, and cluster data for drill-down.

Endpoints:
    GET /api/domain/ir  -- D3-ready graph derived from the domain IR
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from protean.ir.builder import IRBuilder
from protean.ir.generators.base import (
    build_cmd_type_to_fqn,
    build_evt_type_to_fqn,
    short_name,
)
from protean.utils.inflection import titleize

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Explicit mapping from IR element type keys to stat names (avoids
# naive pluralization — e.g. ENTITY → "entities", not "entitys").
_STAT_KEY_MAP: dict[str, str] = {
    "COMMAND": "commands",
    "COMMAND_HANDLER": "command_handlers",
    "DOMAIN_SERVICE": "domain_services",
    "ENTITY": "entities",
    "EVENT": "events",
    "EVENT_HANDLER": "event_handlers",
    "PROCESS_MANAGER": "process_managers",
    "SUBSCRIBER": "subscribers",
    "VALUE_OBJECT": "value_objects",
}


# ---------------------------------------------------------------------------
# IR → D3 graph transformation
# ---------------------------------------------------------------------------


def _build_event_to_agg_index(clusters: dict[str, Any]) -> dict[str, str]:
    """Build a mapping from event ``__type__`` to source aggregate FQN.

    Used by both link detection and PM graph building to determine which
    aggregate originally raised each event.
    """
    event_to_agg: dict[str, str] = {}
    for agg_fqn, cluster in clusters.items():
        for evt in cluster.get("events", {}).values():
            type_key = evt.get("__type__", "")
            if type_key:
                event_to_agg[type_key] = agg_fqn
    return event_to_agg


def _build_graph(ir: dict[str, Any]) -> dict[str, Any]:
    """Transform a raw IR dict into a D3-ready graph structure.

    Returns:
        {
            "nodes": [...],      # One per aggregate
            "links": [...],      # Cross-aggregate edges
            "clusters": {...},   # Full cluster data for drill-down
            "flows": {...},      # Process managers, domain services, subscribers
            "projections": {...},# Projections with source aggregates
            "stats": {...},      # Element counts
            "flow_graph": {...}, # DAG for event flows
            "pm_graphs": [...],  # State machine graphs per process manager
        }
    """
    clusters = ir.get("clusters", {})
    flows = ir.get("flows", {})
    projections = ir.get("projections", {})

    event_to_agg = _build_event_to_agg_index(clusters)

    nodes = _build_nodes(clusters)
    links = _build_links(clusters, flows, event_to_agg)
    stats = _build_stats(ir)
    flow_graph = _build_flow_graph(ir)
    pm_graphs = _build_pm_graphs(flows, event_to_agg)

    return {
        "nodes": nodes,
        "links": links,
        "clusters": clusters,
        "flows": flows,
        "projections": projections,
        "stats": stats,
        "flow_graph": flow_graph,
        "pm_graphs": pm_graphs,
    }


def _build_nodes(clusters: dict[str, Any]) -> list[dict[str, Any]]:
    """Build one node per aggregate with element counts."""
    nodes: list[dict[str, Any]] = []
    for agg_fqn, cluster in clusters.items():
        agg = cluster.get("aggregate", {})
        options = agg.get("options", {})

        # Count elements in this cluster
        counts: dict[str, int] = {}
        for section in (
            "commands",
            "events",
            "entities",
            "value_objects",
            "command_handlers",
            "event_handlers",
            "repositories",
            "application_services",
            "database_models",
        ):
            count = len(cluster.get(section, {}))
            if count > 0:
                counts[section] = count

        nodes.append(
            {
                "id": agg_fqn,
                "name": agg.get("name", short_name(agg_fqn)),
                "type": "aggregate",
                "fqn": agg_fqn,
                "stream_category": options.get("stream_category", ""),
                "is_event_sourced": options.get("is_event_sourced", False),
                "counts": counts,
            }
        )
    return nodes


def _append_link(
    links: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    key: tuple[str, str, str],
    link: dict[str, Any],
) -> None:
    """Append ``link`` unless a link with the same ``key`` is already present."""
    if key not in seen:
        seen.add(key)
        links.append(link)


def _add_event_handler_links(
    clusters: dict[str, Any],
    event_to_agg: dict[str, str],
    links: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    # Cross-aggregate event handlers: handler belongs to agg B but
    # listens to events from agg A (via source_stream or handler map)
    for agg_fqn, cluster in clusters.items():
        for eh in cluster.get("event_handlers", {}).values():
            for type_key in eh.get("handlers", {}):
                source_agg = event_to_agg.get(type_key)
                if source_agg and source_agg != agg_fqn:
                    _append_link(
                        links,
                        seen,
                        (source_agg, agg_fqn, type_key),
                        {
                            "source": source_agg,
                            "target": agg_fqn,
                            "type": "event",
                            "label": _event_name_from_type(type_key),
                        },
                    )


def _add_process_manager_links(
    flows: dict[str, Any],
    event_to_agg: dict[str, str],
    links: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
) -> None:
    # Process managers span multiple aggregates — create undirected edges
    # between all aggregate pairs the PM touches (sorted alphabetically,
    # since PM event flow is non-directional from the IR's perspective).
    for pm_fqn, pm in flows.get("process_managers", {}).items():
        pm_aggs: set[str] = set()
        for type_key in pm.get("handlers", {}):
            source_agg = event_to_agg.get(type_key)
            if source_agg:
                pm_aggs.add(source_agg)
        agg_list = sorted(pm_aggs)
        for i, src in enumerate(agg_list):
            for tgt in agg_list[i + 1 :]:
                _append_link(
                    links,
                    seen,
                    (src, tgt, f"pm:{pm_fqn}"),
                    {
                        "source": src,
                        "target": tgt,
                        "type": "process_manager",
                        "label": pm.get("name", ""),
                    },
                )


def _build_links(
    clusters: dict[str, Any],
    flows: dict[str, Any],
    event_to_agg: dict[str, str],
) -> list[dict[str, Any]]:
    """Detect cross-aggregate edges from event handlers and process managers.

    Only emits links between aggregate nodes (not projections) so every
    link source/target exists in the ``nodes`` list.
    """
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    _add_event_handler_links(clusters, event_to_agg, links, seen)
    _add_process_manager_links(flows, event_to_agg, links, seen)

    return links


def _add_flow_node(
    nodes: list[dict[str, Any]],
    node_ids: set[str],
    node_id: str,
    name: str,
    node_type: str,
    cluster: str = "",
    **extra: Any,
) -> None:
    """Append a flow-graph node unless ``node_id`` is already in ``node_ids``."""
    if node_id in node_ids:
        return
    node_ids.add(node_id)
    node: dict[str, Any] = {
        "id": node_id,
        "name": name,
        "type": node_type,
        "cluster": cluster,
    }
    node.update(extra)
    nodes.append(node)


def _add_cluster_flow_nodes(
    agg_fqn: str,
    cluster_data: dict[str, Any],
    nodes: list[dict[str, Any]],
    node_ids: set[str],
    evt_fqn_to_cluster: dict[str, str],
) -> None:
    """Add one cluster's nodes and record each of its events in ``evt_fqn_to_cluster``.

    Fact events are recorded in the index but get no node.
    """
    agg = cluster_data.get("aggregate", {})
    agg_name = agg.get("name", short_name(agg_fqn))
    _add_flow_node(nodes, node_ids, agg_fqn, agg_name, "aggregate", cluster=agg_fqn)

    for cmd_fqn in cluster_data.get("commands", {}):
        _add_flow_node(
            nodes, node_ids, cmd_fqn, short_name(cmd_fqn), "command", cluster=agg_fqn
        )

    for evt_fqn, evt in cluster_data.get("events", {}).items():
        evt_fqn_to_cluster[evt_fqn] = agg_fqn
        if evt.get("is_fact_event"):
            continue
        _add_flow_node(
            nodes,
            node_ids,
            evt_fqn,
            short_name(evt_fqn),
            "event",
            cluster=agg_fqn,
            published=evt.get("published", False),
        )

    for ch_fqn in cluster_data.get("command_handlers", {}):
        _add_flow_node(
            nodes,
            node_ids,
            ch_fqn,
            short_name(ch_fqn),
            "command_handler",
            cluster=agg_fqn,
        )

    for eh_fqn in cluster_data.get("event_handlers", {}):
        _add_flow_node(
            nodes,
            node_ids,
            eh_fqn,
            short_name(eh_fqn),
            "event_handler",
            cluster=agg_fqn,
        )


def _collect_flow_nodes(
    clusters: dict[str, Any],
    flows: dict[str, Any],
    projections: dict[str, Any],
    nodes: list[dict[str, Any]],
    node_ids: set[str],
) -> dict[str, str]:
    """Add every flow-graph node and return the event FQN to cluster index."""
    evt_fqn_to_cluster: dict[str, str] = {}

    for agg_fqn, cluster_data in clusters.items():
        _add_cluster_flow_nodes(
            agg_fqn, cluster_data, nodes, node_ids, evt_fqn_to_cluster
        )

    for pm_fqn, pm in flows.get("process_managers", {}).items():
        _add_flow_node(
            nodes,
            node_ids,
            pm_fqn,
            pm.get("name", short_name(pm_fqn)),
            "process_manager",
        )

    for proj_group in projections.values():
        for projector_fqn, projector in proj_group.get("projectors", {}).items():
            _add_flow_node(
                nodes,
                node_ids,
                projector_fqn,
                short_name(projector_fqn),
                "projector",
                projection=short_name(projector.get("projector_for", projector_fqn)),
            )

    return evt_fqn_to_cluster


def _add_command_handler_edges(
    agg_fqn: str,
    cluster_data: dict[str, Any],
    node_ids: set[str],
    cmd_type_to_fqn: dict[str, str],
    edges: list[dict[str, Any]],
) -> None:
    for ch_fqn, ch in cluster_data.get("command_handlers", {}).items():
        for type_key in ch.get("handlers", {}):
            cmd_fqn = cmd_type_to_fqn.get(type_key)
            if cmd_fqn and cmd_fqn in node_ids:
                edges.append({"source": cmd_fqn, "target": ch_fqn, "type": "command"})
        edges.append({"source": ch_fqn, "target": agg_fqn, "type": "handler_to_agg"})


def _add_raises_edges(
    agg_fqn: str,
    cluster_data: dict[str, Any],
    edges: list[dict[str, Any]],
) -> None:
    for evt_fqn, evt in cluster_data.get("events", {}).items():
        if evt.get("is_fact_event"):
            continue
        edges.append({"source": agg_fqn, "target": evt_fqn, "type": "raises"})


def _add_event_handler_edges(
    agg_fqn: str,
    cluster_data: dict[str, Any],
    node_ids: set[str],
    evt_type_to_fqn: dict[str, str],
    evt_fqn_to_cluster: dict[str, str],
    edges: list[dict[str, Any]],
) -> None:
    for eh_fqn, eh in cluster_data.get("event_handlers", {}).items():
        for type_key in eh.get("handlers", {}):
            evt_fqn = evt_type_to_fqn.get(type_key)
            if evt_fqn and evt_fqn in node_ids:
                edges.append(
                    {
                        "source": evt_fqn,
                        "target": eh_fqn,
                        "type": "event",
                        "cross_aggregate": (evt_fqn_to_cluster.get(evt_fqn) != agg_fqn),
                    }
                )


def _add_process_manager_edges(
    flows: dict[str, Any],
    node_ids: set[str],
    evt_type_to_fqn: dict[str, str],
    edges: list[dict[str, Any]],
) -> None:
    for pm_fqn, pm in flows.get("process_managers", {}).items():
        for type_key, handler_info in pm.get("handlers", {}).items():
            evt_fqn = evt_type_to_fqn.get(type_key)
            if evt_fqn and evt_fqn in node_ids:
                edges.append(
                    {
                        "source": evt_fqn,
                        "target": pm_fqn,
                        "type": "event",
                        "start": handler_info.get("start", False),
                        "end": handler_info.get("end", False),
                    }
                )


def _add_projector_edges(
    projections: dict[str, Any],
    node_ids: set[str],
    evt_type_to_fqn: dict[str, str],
    edges: list[dict[str, Any]],
) -> None:
    for proj_group in projections.values():
        for projector_fqn, projector in proj_group.get("projectors", {}).items():
            for type_key in projector.get("handlers", {}):
                evt_fqn = evt_type_to_fqn.get(type_key)
                if evt_fqn and evt_fqn in node_ids:
                    edges.append(
                        {
                            "source": evt_fqn,
                            "target": projector_fqn,
                            "type": "projection",
                        }
                    )


def _build_flow_graph(ir: dict[str, Any]) -> dict[str, Any]:
    """Build a detailed DAG for the event flow view.

    Returns a graph with individual nodes for commands, command handlers,
    aggregates, events, event handlers, process managers, and projectors,
    plus directed edges showing the message flow between them.

    Uses two passes: first collects all nodes, then creates edges
    (ensuring all referenced nodes exist regardless of iteration order).
    """
    clusters = ir.get("clusters", {})
    flows = ir.get("flows", {})
    projections = ir.get("projections", {})

    cmd_type_to_fqn = build_cmd_type_to_fqn(ir)
    evt_type_to_fqn = build_evt_type_to_fqn(ir)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    # --- Pass 1: Collect all nodes + build event→cluster index ---

    evt_fqn_to_cluster = _collect_flow_nodes(
        clusters, flows, projections, nodes, node_ids
    )

    # --- Pass 2: Create edges ---

    for agg_fqn, cluster_data in clusters.items():
        _add_command_handler_edges(
            agg_fqn, cluster_data, node_ids, cmd_type_to_fqn, edges
        )
        _add_raises_edges(agg_fqn, cluster_data, edges)
        _add_event_handler_edges(
            agg_fqn,
            cluster_data,
            node_ids,
            evt_type_to_fqn,
            evt_fqn_to_cluster,
            edges,
        )

    _add_process_manager_edges(flows, node_ids, evt_type_to_fqn, edges)
    _add_projector_edges(projections, node_ids, evt_type_to_fqn, edges)

    return {"nodes": nodes, "edges": edges}


_PMHandlerEntry = tuple[str, dict[str, Any]]


def _classify_pm_handlers(
    handlers: dict[str, Any],
    event_to_agg: dict[str, str],
) -> tuple[
    list[_PMHandlerEntry], list[_PMHandlerEntry], list[_PMHandlerEntry], set[str]
]:
    """Split a PM's handlers into start, end and mid lists, sorted by type key.

    Also returns the set of aggregate FQNs that raise the handled events.
    """
    agg_set: set[str] = set()
    start_events: list[_PMHandlerEntry] = []
    end_events: list[_PMHandlerEntry] = []
    mid_events: list[_PMHandlerEntry] = []

    for type_key, handler_info in sorted(handlers.items()):
        is_start = handler_info.get("start", False)
        is_end = handler_info.get("end", False)
        entry = (type_key, handler_info)
        if is_start:
            start_events.append(entry)
        elif is_end:
            end_events.append(entry)
        else:
            mid_events.append(entry)

        agg_fqn = event_to_agg.get(type_key)
        if agg_fqn:
            agg_set.add(agg_fqn)

    return start_events, end_events, mid_events, agg_set


def _add_pm_state(
    states: list[dict[str, Any]],
    state_ids: set[str],
    sid: str,
    label: str,
    state_type: str,
) -> None:
    if sid not in state_ids:
        state_ids.add(sid)
        states.append({"id": sid, "label": label, "type": state_type})


def _add_pm_start_transitions(
    start_events: list[_PMHandlerEntry],
    states: list[dict[str, Any]],
    state_ids: set[str],
    transitions: list[dict[str, Any]],
) -> None:
    for type_key, handler_info in start_events:
        if handler_info.get("end", False):
            _add_pm_state(states, state_ids, "completed", "Completed", "end")
            transitions.append(
                _make_transition("initial", "completed", type_key, handler_info)
            )
        else:
            target_id = f"after:{type_key}"
            _add_pm_state(
                states,
                state_ids,
                target_id,
                _state_label_from_event(type_key),
                "intermediate",
            )
            transitions.append(
                _make_transition("initial", target_id, type_key, handler_info)
            )


def _build_pm_graph(
    pm_fqn: str,
    pm: dict[str, Any],
    event_to_agg: dict[str, str],
) -> dict[str, Any]:
    """Build the state machine graph for one process manager."""
    handlers = pm.get("handlers", {})
    if not handlers:
        return {
            "fqn": pm_fqn,
            "name": pm.get("name", short_name(pm_fqn)),
            "stream_categories": pm.get("stream_categories", []),
            "states": [],
            "transitions": [],
            "aggregates": [],
        }

    states: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    state_ids: set[str] = set()

    # Classify handlers by lifecycle
    start_events, end_events, mid_events, agg_set = _classify_pm_handlers(
        handlers, event_to_agg
    )

    _add_pm_state(states, state_ids, "initial", "Initial", "start")

    # Build transitions from start events
    _add_pm_start_transitions(start_events, states, state_ids, transitions)

    # Build transitions for mid events — chains from the last
    # start state(s) through each mid-event sequentially.
    prev_states = [f"after:{tk}" for tk, hi in start_events if not hi.get("end", False)]
    if not prev_states:
        prev_states = ["initial"]

    for type_key, handler_info in mid_events:
        target_id = f"after:{type_key}"
        _add_pm_state(
            states,
            state_ids,
            target_id,
            _state_label_from_event(type_key),
            "intermediate",
        )
        transitions.extend(
            _make_transition(prev, target_id, type_key, handler_info)
            for prev in prev_states
        )
        prev_states = [target_id]

    # Build transitions for end events
    if end_events:
        _add_pm_state(states, state_ids, "completed", "Completed", "end")
        for type_key, handler_info in end_events:
            transitions.extend(
                _make_transition(src, "completed", type_key, handler_info)
                for src in prev_states
            )

    return {
        "fqn": pm_fqn,
        "name": pm.get("name", short_name(pm_fqn)),
        "stream_categories": pm.get("stream_categories", []),
        "states": states,
        "transitions": transitions,
        "aggregates": sorted(short_name(a) for a in agg_set),
    }


def _build_pm_graphs(
    flows: dict[str, Any],
    event_to_agg: dict[str, str],
) -> list[dict[str, Any]]:
    """Build state machine graphs for each process manager.

    Derives states from handler lifecycle metadata (start/end flags)
    and the events that trigger transitions. Each PM produces a graph
    with state nodes and event-labeled transition edges.

    The states are inferred as follows:
    - A start handler event creates a transition from the "initial" state
    - An end handler event creates a transition to a "completed" state
    - Other handler events create transitions between intermediate states
    - Intermediate states are named after the triggering event

    Returns a list of PM graph dicts, one per process manager.
    """
    pms = flows.get("process_managers", {})
    if not pms:
        return []

    return [
        _build_pm_graph(pm_fqn, pm, event_to_agg) for pm_fqn, pm in sorted(pms.items())
    ]


def _event_name_from_type(type_key: str) -> str:
    """Extract the event class name from an event ``__type__`` string.

    The ``__type__`` format is ``{Category}.{EventName}.{Version}``
    (e.g. ``Ordering.OrderPlaced.v1``).  Returns the middle segment
    (``OrderPlaced``), or the full string if it has fewer than 3 parts.
    """
    parts = type_key.split(".")
    if len(parts) >= 3:
        return parts[-2]
    return parts[0] if parts else type_key


def _make_transition(
    source: str,
    target: str,
    type_key: str,
    handler_info: dict[str, Any],
) -> dict[str, Any]:
    """Build a single transition edge dict for the PM state machine."""
    return {
        "source": source,
        "target": target,
        "event": _event_name_from_type(type_key),
        "event_type": type_key,
        "methods": handler_info.get("methods", []),
    }


def _state_label_from_event(type_key: str) -> str:
    """Derive a human-readable state label from an event ``__type__`` string.

    E.g. ``Ordering.OrderPlaced.v1`` → ``Order Placed``.
    """
    return titleize(_event_name_from_type(type_key))


def _build_stats(ir: dict[str, Any]) -> dict[str, int]:
    """Compute summary statistics from the IR."""
    elements = ir.get("elements", {})
    clusters = ir.get("clusters", {})
    projections = ir.get("projections", {})
    diagnostics = ir.get("diagnostics", [])

    stats: dict[str, int] = {
        "aggregates": len(clusters),
        "projections": len(projections),
    }

    for ir_key, stat_key in _STAT_KEY_MAP.items():
        stats[stat_key] = len(elements.get(ir_key, []))

    stats["handlers"] = (
        stats.get("command_handlers", 0)
        + stats.get("event_handlers", 0)
        + stats.get("process_managers", 0)
    )
    stats["diagnostics"] = len(diagnostics)

    return stats


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_domain_router(domains: list[Domain]) -> APIRouter:
    """Create the /domain API router.

    The domain IR is computed once at startup and cached — domain
    topology is immutable at runtime and cannot change without a
    server restart.
    """
    router = APIRouter()

    # Pre-compute the D3 graph at startup (topology is static).
    # Gracefully degrade if IR building fails (e.g. mock domains in tests).
    _cached_graph: dict[str, Any] | None = None
    if domains:
        try:
            domain = domains[0]
            with domain.domain_context():
                ir = IRBuilder(domain).build()
            _cached_graph = _build_graph(ir)
        # the IR endpoint answers unavailable instead of crashing; logged
        except Exception:
            logger.warning("Failed to build domain IR graph", exc_info=True)

    @router.get("/domain/ir")
    async def domain_ir() -> JSONResponse:
        """Domain IR transformed into a D3-ready graph structure."""
        if _cached_graph is None:
            return JSONResponse(
                content={"error": "Domain IR unavailable"},
                status_code=503,
            )
        return JSONResponse(content=_cached_graph)

    return router
