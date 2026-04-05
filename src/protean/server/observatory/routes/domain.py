"""Domain visualization API for the Protean Observatory.

Transforms the domain's IR into a D3-ready graph structure with
aggregate nodes, cross-aggregate edges, and cluster data for drill-down.

Endpoints:
    GET /domain/ir  -- D3-ready graph derived from the domain IR
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from protean.ir.generators.base import short_name

if TYPE_CHECKING:
    from protean.domain import Domain

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
    links = _build_links(clusters, flows, projections)
    stats = _build_stats(elements, clusters, flows, projections)

    return {
        "nodes": nodes,
        "links": links,
        "clusters": clusters,
        "flows": flows,
        "projections": projections,
        "stats": stats,
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
    projections: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect cross-aggregate edges from event handlers, PMs, and projectors."""
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
    for _pm_fqn, pm in flows.get("process_managers", {}).items():
        pm_aggs: set[str] = set()
        for type_key in pm.get("handlers", {}):
            source_agg = event_to_agg.get(type_key)
            if source_agg:
                pm_aggs.add(source_agg)
        agg_list = sorted(pm_aggs)
        for i, src in enumerate(agg_list):
            for tgt in agg_list[i + 1 :]:
                key = (src, tgt, f"pm:{pm.get('name', '')}")
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

    # Projectors: link source aggregates to the projection
    for _proj_fqn, proj_data in projections.items():
        for _projector_fqn, projector in proj_data.get("projectors", {}).items():
            for type_key in projector.get("handlers", {}):
                source_agg = event_to_agg.get(type_key)
                if source_agg:
                    key = (source_agg, _proj_fqn, f"proj:{type_key}")
                    if key not in seen:
                        seen.add(key)
                        links.append(
                            {
                                "source": source_agg,
                                "target": _proj_fqn,
                                "type": "projection",
                                "label": short_name(type_key),
                            }
                        )

    return links


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
            pass

    @router.get("/domain/ir")
    async def domain_ir() -> JSONResponse:
        """Domain IR transformed into a D3-ready graph structure."""
        if _cached_graph is None:
            return JSONResponse(
                content={"error": "No domains registered"},
                status_code=503,
            )
        return JSONResponse(content=_cached_graph)

    return router
