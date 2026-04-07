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

from protean.ir.generators.base import (
    build_cmd_type_to_fqn,
    build_evt_type_to_fqn,
    short_name,
)

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
        }
    """
    clusters = ir.get("clusters", {})
    flows = ir.get("flows", {})
    projections = ir.get("projections", {})
    elements = ir.get("elements", {})

    nodes = _build_nodes(clusters)
    links = _build_links(clusters, flows)
    stats = _build_stats(elements, clusters, flows, projections)
    flow_graph = _build_flow_graph(ir)

    return {
        "nodes": nodes,
        "links": links,
        "clusters": clusters,
        "flows": flows,
        "projections": projections,
        "stats": stats,
        "flow_graph": flow_graph,
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


def _build_links(
    clusters: dict[str, Any],
    flows: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect cross-aggregate edges from event handlers and process managers.

    Only emits links between aggregate nodes (not projections) so every
    link source/target exists in the ``nodes`` list.
    """
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    # Index: event __type__ → source aggregate FQN
    event_to_agg: dict[str, str] = {}
    for agg_fqn, cluster in clusters.items():
        for _evt_fqn, evt in cluster.get("events", {}).items():
            type_key = evt.get("__type__", "")
            if type_key:
                event_to_agg[type_key] = agg_fqn

    # Cross-aggregate event handlers: handler belongs to agg B but
    # listens to events from agg A (via source_stream or handler map)
    for agg_fqn, cluster in clusters.items():
        for _eh_fqn, eh in cluster.get("event_handlers", {}).items():
            for type_key in eh.get("handlers", {}):
                source_agg = event_to_agg.get(type_key)
                if source_agg and source_agg != agg_fqn:
                    key = (source_agg, agg_fqn, type_key)
                    if key not in seen:
                        seen.add(key)
                        links.append(
                            {
                                "source": source_agg,
                                "target": agg_fqn,
                                "type": "event",
                                "label": short_name(type_key),
                            }
                        )

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
                key = (src, tgt, f"pm:{pm_fqn}")
                if key not in seen:
                    seen.add(key)
                    links.append(
                        {
                            "source": src,
                            "target": tgt,
                            "type": "process_manager",
                            "label": pm.get("name", ""),
                        }
                    )

    return links


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

    def _add_node(
        node_id: str,
        name: str,
        node_type: str,
        cluster: str = "",
        **extra: Any,
    ) -> None:
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

    # --- Pass 1: Collect all nodes + build event→cluster index ---

    evt_fqn_to_cluster: dict[str, str] = {}

    for agg_fqn, cluster_data in clusters.items():
        agg = cluster_data.get("aggregate", {})
        agg_name = agg.get("name", short_name(agg_fqn))
        _add_node(agg_fqn, agg_name, "aggregate", cluster=agg_fqn)

        for cmd_fqn in cluster_data.get("commands", {}):
            _add_node(cmd_fqn, short_name(cmd_fqn), "command", cluster=agg_fqn)

        for evt_fqn, evt in cluster_data.get("events", {}).items():
            evt_fqn_to_cluster[evt_fqn] = agg_fqn
            if evt.get("is_fact_event"):
                continue
            _add_node(
                evt_fqn,
                short_name(evt_fqn),
                "event",
                cluster=agg_fqn,
                published=evt.get("published", False),
            )

        for ch_fqn in cluster_data.get("command_handlers", {}):
            _add_node(ch_fqn, short_name(ch_fqn), "command_handler", cluster=agg_fqn)

        for eh_fqn in cluster_data.get("event_handlers", {}):
            _add_node(eh_fqn, short_name(eh_fqn), "event_handler", cluster=agg_fqn)

    for pm_fqn, pm in flows.get("process_managers", {}).items():
        _add_node(pm_fqn, pm.get("name", short_name(pm_fqn)), "process_manager")

    for _proj_fqn, proj_group in projections.items():
        for projector_fqn, projector in proj_group.get("projectors", {}).items():
            _add_node(
                projector_fqn,
                short_name(projector_fqn),
                "projector",
                projection=short_name(projector.get("projector_for", projector_fqn)),
            )

    # --- Pass 2: Create edges ---

    for agg_fqn, cluster_data in clusters.items():
        # Command Handler edges
        for ch_fqn, ch in cluster_data.get("command_handlers", {}).items():
            for type_key in ch.get("handlers", {}):
                cmd_fqn = cmd_type_to_fqn.get(type_key)
                if cmd_fqn and cmd_fqn in node_ids:
                    edges.append(
                        {"source": cmd_fqn, "target": ch_fqn, "type": "command"}
                    )
            edges.append(
                {"source": ch_fqn, "target": agg_fqn, "type": "handler_to_agg"}
            )

        # Aggregate → Event edges
        for evt_fqn, evt in cluster_data.get("events", {}).items():
            if evt.get("is_fact_event"):
                continue
            edges.append({"source": agg_fqn, "target": evt_fqn, "type": "raises"})

        # Event handler edges
        for eh_fqn, eh in cluster_data.get("event_handlers", {}).items():
            for type_key in eh.get("handlers", {}):
                evt_fqn = evt_type_to_fqn.get(type_key)
                if evt_fqn and evt_fqn in node_ids:
                    edges.append(
                        {
                            "source": evt_fqn,
                            "target": eh_fqn,
                            "type": "event",
                            "cross_aggregate": (
                                evt_fqn_to_cluster.get(evt_fqn) != agg_fqn
                            ),
                        }
                    )

    # Process manager edges
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

    # Projector edges
    for _proj_fqn, proj_group in projections.items():
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

    return {"nodes": nodes, "edges": edges}


def _build_stats(
    elements: dict[str, list[str]],
    clusters: dict[str, Any],
    flows: dict[str, Any],
    projections: dict[str, Any],
) -> dict[str, int]:
    """Compute summary statistics from the IR."""
    stats: dict[str, int] = {
        "aggregates": len(clusters),
        "projections": len(projections),
    }

    for ir_key, stat_key in _STAT_KEY_MAP.items():
        stats[stat_key] = len(elements.get(ir_key, []))

    return stats


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_domain_router(domains: list["Domain"]) -> APIRouter:
    """Create the /domain API router.

    The domain IR is computed once at startup and cached — domain
    topology is immutable at runtime and cannot change without a
    server restart.
    """
    from protean.ir.builder import IRBuilder

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
