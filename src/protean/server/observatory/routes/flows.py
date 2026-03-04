"""Event flow graph and causation trace API for the Protean Observatory.

Provides two categories of endpoints:

1. **Flow Graph** — Static domain topology derived from ``domain.to_ir()``.
   Nodes (commands, events, handlers, aggregates) and edges (handles,
   subscribes, raises) are transformed into a D3-friendly JSON graph.

2. **Causation Trace** — Runtime message traces via the event store's
   ``build_causation_tree()`` API.  Given a correlation ID the endpoint
   returns a tree of ``CausationNode`` objects.

Endpoints:
    GET /flows/graph                    — D3-friendly directed graph
    GET /flows/trace/{correlation_id}   — Causation tree for a correlation
    GET /flows/element/{fqn}            — Single IR element by FQN
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Module-level IR cache: domain name → IR dict.
# IR is stable at runtime so no TTL is needed.
_ir_cache: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def get_cached_ir(domain: "Domain") -> dict[str, Any]:
    """Return the IR for *domain*, caching it on first access."""
    name = domain.name
    if name not in _ir_cache:
        _ir_cache[name] = domain.to_ir()
    return _ir_cache[name]


def clear_ir_cache() -> None:
    """Clear the IR cache (useful in tests)."""
    _ir_cache.clear()


def _short_name(type_str: str) -> str:
    """Extract the short class name from a ``__type__`` string.

    ``"MyApp.OrderPlaced.v1"`` → ``"OrderPlaced"``
    """
    parts = type_str.rsplit(".", 2)
    if len(parts) >= 2:
        return parts[-2]
    return type_str


def ir_to_graph(ir: dict[str, Any]) -> dict[str, Any]:
    """Transform an IR dict into a D3-friendly directed graph.

    Returns::

        {
            "nodes": [{"id": ..., "label": ..., "type": ..., "aggregate": ...}, ...],
            "edges": [{"source": ..., "target": ..., "type": ...}, ...],
            "clusters": ["Order", "Inventory", ...]
        }

    Node types:
        aggregate, command, event, command_handler, event_handler,
        projector, process_manager, subscriber, domain_service

    Edge types:
        handles   — command → command_handler
        raises    — cluster membership (events belong to aggregate)
        subscribes — event → event_handler / projector / PM
        projects  — projector → projection
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    cluster_names: list[str] = []

    def _add_node(
        node_id: str,
        label: str,
        node_type: str,
        aggregate: str | None = None,
        **extra: Any,
    ) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        node: dict[str, Any] = {
            "id": node_id,
            "label": label,
            "type": node_type,
        }
        if aggregate:
            node["aggregate"] = aggregate
        node.update(extra)
        nodes.append(node)

    def _add_edge(source: str, target: str, edge_type: str, **extra: Any) -> None:
        edge: dict[str, Any] = {
            "source": source,
            "target": target,
            "type": edge_type,
        }
        edge.update(extra)
        edges.append(edge)

    # ----- 1. Walk clusters (aggregates with commands, events, handlers) -----
    clusters = ir.get("clusters", {})
    for agg_fqn, cluster in clusters.items():
        agg_info = cluster.get("aggregate", {})
        agg_name = agg_info.get("name", agg_fqn)
        cluster_names.append(agg_name)
        _add_node(agg_fqn, agg_name, "aggregate")

        # Commands
        for cmd_fqn, cmd_info in cluster.get("commands", {}).items():
            cmd_type = cmd_info.get("__type__", cmd_fqn)
            cmd_label = cmd_info.get("name", _short_name(cmd_type))
            _add_node(cmd_type, cmd_label, "command", aggregate=agg_name, fqn=cmd_fqn)

        # Events
        for evt_fqn, evt_info in cluster.get("events", {}).items():
            evt_type = evt_info.get("__type__", evt_fqn)
            evt_label = evt_info.get("name", _short_name(evt_type))
            _add_node(evt_type, evt_label, "event", aggregate=agg_name, fqn=evt_fqn)

        # Command handlers
        for ch_fqn, ch_info in cluster.get("command_handlers", {}).items():
            ch_label = ch_info.get("name", ch_fqn)
            _add_node(ch_fqn, ch_label, "command_handler", aggregate=agg_name)

            # Edges: each handled __type__ → this handler
            for handled_type in ch_info.get("handlers", {}):
                if handled_type in node_ids or handled_type.startswith("$"):
                    pass  # add edge below after all nodes are created
                _add_edge(handled_type, ch_fqn, "handles")

        # Event handlers
        for eh_fqn, eh_info in cluster.get("event_handlers", {}).items():
            eh_label = eh_info.get("name", eh_fqn)
            _add_node(eh_fqn, eh_label, "event_handler", aggregate=agg_name)

            for handled_type in eh_info.get("handlers", {}):
                if not handled_type.startswith("$"):
                    _add_edge(handled_type, eh_fqn, "subscribes")

    # ----- 2. Walk flows (process managers, subscribers, domain services) ----
    flows = ir.get("flows", {})

    for pm_fqn, pm_info in flows.get("process_managers", {}).items():
        pm_label = pm_info.get("name", pm_fqn)
        _add_node(pm_fqn, pm_label, "process_manager")

        for handled_type in pm_info.get("handlers", {}):
            if not handled_type.startswith("$"):
                _add_edge(handled_type, pm_fqn, "subscribes")

    for sub_fqn, sub_info in flows.get("subscribers", {}).items():
        sub_label = sub_info.get("name", sub_fqn)
        _add_node(sub_fqn, sub_label, "subscriber")

    for ds_fqn, ds_info in flows.get("domain_services", {}).items():
        ds_label = ds_info.get("name", ds_fqn)
        _add_node(ds_fqn, ds_label, "domain_service")

    # ----- 3. Walk projections (projector → projection edges) ---------------
    projections = ir.get("projections", {})
    for proj_fqn, proj_group in projections.items():
        proj_info = proj_group.get("projection", {})
        proj_label = proj_info.get("name", proj_fqn)
        _add_node(proj_fqn, proj_label, "projection")

        for ptor_fqn, ptor_info in proj_group.get("projectors", {}).items():
            ptor_label = ptor_info.get("name", ptor_fqn)
            _add_node(ptor_fqn, ptor_label, "projector")
            _add_edge(ptor_fqn, proj_fqn, "projects")

            # Edges: each handled event → this projector
            for handled_type in ptor_info.get("handlers", {}):
                if not handled_type.startswith("$"):
                    _add_edge(handled_type, ptor_fqn, "subscribes")

    # Filter out edges whose source/target doesn't exist as a node
    valid_edges = [
        e for e in edges if e["source"] in node_ids and e["target"] in node_ids
    ]

    return {
        "nodes": nodes,
        "edges": valid_edges,
        "clusters": sorted(cluster_names),
    }


def causation_node_to_dict(node: Any) -> dict[str, Any]:
    """Recursively convert a ``CausationNode`` to a JSON-serializable dict."""
    return {
        "message_id": node.message_id,
        "message_type": node.message_type,
        "kind": node.kind,
        "stream": node.stream,
        "time": node.time,
        "global_position": node.global_position,
        "children": [causation_node_to_dict(c) for c in (node.children or [])],
    }


def _find_element_by_fqn(ir: dict[str, Any], fqn: str) -> dict[str, Any] | None:
    """Search the IR for an element matching *fqn*.

    Looks through clusters (all sections), flows (all sections), and
    projections (projection + projectors).
    """
    # Search clusters
    for _agg_fqn, cluster in ir.get("clusters", {}).items():
        for section_name in (
            "aggregate",
            "commands",
            "events",
            "command_handlers",
            "event_handlers",
            "entities",
            "value_objects",
            "repositories",
            "application_services",
            "database_models",
        ):
            section = cluster.get(section_name)
            if section is None:
                continue
            if isinstance(section, dict) and "fqn" in section:
                # Scalar section (e.g. "aggregate")
                if section.get("fqn") == fqn:
                    return section
            elif isinstance(section, dict):
                # Dict of fqn → element
                if fqn in section:
                    return section[fqn]

    # Search flows
    for _section_name in ("domain_services", "process_managers", "subscribers"):
        section = ir.get("flows", {}).get(_section_name, {})
        if fqn in section:
            return section[fqn]

    # Search projections
    for _proj_fqn, proj_group in ir.get("projections", {}).items():
        proj = proj_group.get("projection", {})
        if proj.get("fqn") == fqn:
            return proj
        for sub_section in ("projectors", "queries", "query_handlers"):
            sub = proj_group.get(sub_section, {})
            if fqn in sub:
                return sub[fqn]

    return None


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_flows_router(domains: List["Domain"]) -> APIRouter:
    """Create the /flows API router."""
    router = APIRouter()

    @router.get("/flows/graph")
    async def flow_graph() -> JSONResponse:
        """D3-friendly directed graph of the domain topology."""
        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []
        all_clusters: list[str] = []

        for domain in domains:
            try:
                ir = get_cached_ir(domain)
                graph = ir_to_graph(ir)
                all_nodes.extend(graph["nodes"])
                all_edges.extend(graph["edges"])
                all_clusters.extend(graph["clusters"])
            except Exception:
                logger.debug(
                    "Failed to build IR graph for domain %s",
                    domain.name,
                    exc_info=True,
                )

        return JSONResponse(
            content={
                "nodes": all_nodes,
                "edges": all_edges,
                "clusters": sorted(set(all_clusters)),
            }
        )

    @router.get("/flows/trace/{correlation_id}")
    async def causation_trace(
        correlation_id: str = Path(description="Correlation ID to trace"),
    ) -> JSONResponse:
        """Causation tree for a given correlation ID."""
        for domain in domains:
            try:
                with domain.domain_context():
                    store = domain.event_store.store
                    tree = store.build_causation_tree(correlation_id)
                    if tree is not None:
                        return JSONResponse(
                            content={"tree": causation_node_to_dict(tree)}
                        )
            except Exception:
                logger.debug(
                    "Failed to build causation tree in domain %s",
                    domain.name,
                    exc_info=True,
                )

        return JSONResponse(
            content={
                "error": f"No messages found for correlation_id '{correlation_id}'"
            },
            status_code=404,
        )

    @router.get("/flows/element/{fqn:path}")
    async def element_detail(
        fqn: str = Path(description="Fully qualified name of the element"),
    ) -> JSONResponse:
        """Single IR element by FQN."""
        for domain in domains:
            try:
                ir = get_cached_ir(domain)
                element = _find_element_by_fqn(ir, fqn)
                if element is not None:
                    return JSONResponse(content={"element": element})
            except Exception:
                logger.debug(
                    "Failed to search IR for fqn %s in domain %s",
                    fqn,
                    domain.name,
                    exc_info=True,
                )

        return JSONResponse(
            content={"error": f"Element '{fqn}' not found"},
            status_code=404,
        )

    return router
