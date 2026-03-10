"""Event flow diagram generator.

Produces Mermaid ``flowchart LR`` output from an IR dict, showing the flow
of commands through handlers into aggregates and the events they raise,
with downstream handlers (event handlers, process managers, projectors).

Usage::

    from protean.ir.generators.events import generate_event_flow_diagram

    diagram = generate_event_flow_diagram(ir)
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import (
    mermaid_escape,
    sanitize_mermaid_id,
    short_name,
)


def _cmd_node_id(fqn: str) -> str:
    return f"cmd_{sanitize_mermaid_id(fqn)}"


def _evt_node_id(fqn: str) -> str:
    return f"evt_{sanitize_mermaid_id(fqn)}"


def _handler_node_id(fqn: str) -> str:
    return f"hdlr_{sanitize_mermaid_id(fqn)}"


def _agg_node_id(fqn: str) -> str:
    return f"agg_{sanitize_mermaid_id(fqn)}"


def _pm_node_id(fqn: str) -> str:
    return f"pm_{sanitize_mermaid_id(fqn)}"


def _proj_node_id(fqn: str) -> str:
    return f"proj_{sanitize_mermaid_id(fqn)}"


def _evt_handler_node_id(fqn: str) -> str:
    return f"eh_{sanitize_mermaid_id(fqn)}"


def _build_event_type_to_fqn(ir: dict[str, Any]) -> dict[str, str]:
    """Build a mapping from event __type__ strings to their FQNs."""
    mapping: dict[str, str] = {}
    for cluster in ir.get("clusters", {}).values():
        for evt_fqn, evt in cluster.get("events", {}).items():
            type_str = evt.get("__type__", "")
            if type_str:
                mapping[type_str] = evt_fqn
    return mapping


def _build_cmd_type_to_fqn(ir: dict[str, Any]) -> dict[str, str]:
    """Build a mapping from command __type__ strings to their FQNs."""
    mapping: dict[str, str] = {}
    for cluster in ir.get("clusters", {}).values():
        for cmd_fqn, cmd in cluster.get("commands", {}).items():
            type_str = cmd.get("__type__", "")
            if type_str:
                mapping[type_str] = cmd_fqn
    return mapping


def _render_cluster_subgraph(
    cluster_fqn: str,
    cluster: dict[str, Any],
) -> list[str]:
    """Render a cluster's commands, aggregate, and events as a subgraph."""
    lines: list[str] = []
    agg_short = short_name(cluster_fqn)
    subgraph_id = sanitize_mermaid_id(cluster_fqn)

    lines.append(f"    subgraph {subgraph_id}[{mermaid_escape(agg_short)}]")

    # Aggregate node
    agg_id = _agg_node_id(cluster_fqn)
    lines.append(f"        {agg_id}[{mermaid_escape(agg_short)}]")

    # Command nodes (parallelogram shape)
    for cmd_fqn, cmd in sorted(cluster.get("commands", {}).items()):
        cmd_id = _cmd_node_id(cmd_fqn)
        cmd_short = short_name(cmd_fqn)
        lines.append(f"        {cmd_id}[/{mermaid_escape(cmd_short)}/]")

    # Event nodes (rounded/stadium shape)
    for evt_fqn, evt in sorted(cluster.get("events", {}).items()):
        if evt.get("is_fact_event"):
            continue
        evt_id = _evt_node_id(evt_fqn)
        evt_short = short_name(evt_fqn)
        lines.append(f"        {evt_id}([{mermaid_escape(evt_short)}])")

    # Command handler nodes and edges
    for ch_fqn, ch in sorted(cluster.get("command_handlers", {}).items()):
        ch_id = _handler_node_id(ch_fqn)
        ch_short = short_name(ch_fqn)
        lines.append(f"        {ch_id}[{mermaid_escape(ch_short)}]")

    lines.append("    end")
    return lines


def _render_cluster_edges(
    cluster_fqn: str,
    cluster: dict[str, Any],
    cmd_type_to_fqn: dict[str, str],
) -> list[str]:
    """Render edges within a cluster: cmd -> handler -> agg -> event."""
    lines: list[str] = []
    agg_id = _agg_node_id(cluster_fqn)

    for ch_fqn, ch in sorted(cluster.get("command_handlers", {}).items()):
        ch_id = _handler_node_id(ch_fqn)

        # Commands -> command handler
        for cmd_type in sorted(ch.get("handlers", {}).keys()):
            cmd_fqn = cmd_type_to_fqn.get(cmd_type, "")
            if cmd_fqn:
                lines.append(f"    {_cmd_node_id(cmd_fqn)} --> {ch_id}")

        # Command handler -> aggregate
        lines.append(f"    {ch_id} --> {agg_id}")

    # Aggregate -> events
    for evt_fqn, evt in sorted(cluster.get("events", {}).items()):
        if evt.get("is_fact_event"):
            continue
        lines.append(f"    {agg_id} --> {_evt_node_id(evt_fqn)}")

    return lines


def _render_event_handler_nodes_and_edges(
    ir: dict[str, Any],
    evt_type_to_fqn: dict[str, str],
) -> list[str]:
    """Render event handler nodes and their incoming edges from events."""
    lines: list[str] = []

    for cluster in ir.get("clusters", {}).values():
        for eh_fqn, eh in sorted(cluster.get("event_handlers", {}).items()):
            eh_id = _evt_handler_node_id(eh_fqn)
            eh_short = short_name(eh_fqn)
            lines.append(f"    {eh_id}[{mermaid_escape(eh_short)}]")

            for evt_type in sorted(eh.get("handlers", {}).keys()):
                evt_fqn = evt_type_to_fqn.get(evt_type, "")
                if evt_fqn:
                    lines.append(f"    {_evt_node_id(evt_fqn)} --> {eh_id}")

    return lines


def _render_process_managers(
    ir: dict[str, Any],
    evt_type_to_fqn: dict[str, str],
) -> list[str]:
    """Render process manager nodes and edges."""
    lines: list[str] = []
    pms = ir.get("flows", {}).get("process_managers", {})

    for pm_fqn, pm in sorted(pms.items()):
        pm_id = _pm_node_id(pm_fqn)
        pm_short = short_name(pm_fqn)

        # Collect lifecycle annotations
        annotations: list[str] = []
        for _evt_type, handler_info in sorted(pm.get("handlers", {}).items()):
            if handler_info.get("start"):
                annotations.append("start")
                break
        for _evt_type, handler_info in sorted(pm.get("handlers", {}).items()):
            if handler_info.get("end"):
                annotations.append("end")
                break

        label = pm_short
        if annotations:
            label = f"{pm_short} ({', '.join(annotations)})"

        lines.append(f"    {pm_id}[{mermaid_escape(label)}]")

        # Events -> PM
        for evt_type in sorted(pm.get("handlers", {}).keys()):
            evt_fqn = evt_type_to_fqn.get(evt_type, "")
            if evt_fqn:
                handler_info = pm["handlers"][evt_type]
                edge_label_parts: list[str] = []
                if handler_info.get("start"):
                    edge_label_parts.append("start")
                if handler_info.get("end"):
                    edge_label_parts.append("end")

                if edge_label_parts:
                    edge_label = ", ".join(edge_label_parts)
                    lines.append(
                        f"    {_evt_node_id(evt_fqn)}"
                        f" -->|{mermaid_escape(edge_label)}| {pm_id}"
                    )
                else:
                    lines.append(f"    {_evt_node_id(evt_fqn)} --> {pm_id}")

    return lines


def _render_projectors(
    ir: dict[str, Any],
    evt_type_to_fqn: dict[str, str],
) -> list[str]:
    """Render projector nodes and edges."""
    lines: list[str] = []

    for proj_group in ir.get("projections", {}).values():
        for projector_fqn, projector in sorted(
            proj_group.get("projectors", {}).items()
        ):
            proj_id = _proj_node_id(projector_fqn)
            proj_short = short_name(projector_fqn)
            projection_fqn = projector.get("projector_for", "")
            projection_short = short_name(projection_fqn)

            label = proj_short
            if projection_short:
                label = f"{proj_short} → {projection_short}"

            lines.append(f"    {proj_id}[{mermaid_escape(label)}]")

            # Events -> Projector
            for evt_type in sorted(projector.get("handlers", {}).keys()):
                evt_fqn = evt_type_to_fqn.get(evt_type, "")
                if evt_fqn:
                    lines.append(f"    {_evt_node_id(evt_fqn)} --> {proj_id}")

    return lines


def generate_event_flow_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart LR`` showing event flows.

    The diagram shows the path of commands through handlers into
    aggregates, the events they raise, and the downstream consumers
    (event handlers, process managers, projectors).

    Args:
        ir: The full IR dict.

    Returns:
        A string containing the Mermaid ``flowchart LR`` source.
    """
    clusters = ir.get("clusters", {})
    if not clusters:
        return "flowchart LR"

    evt_type_to_fqn = _build_event_type_to_fqn(ir)
    cmd_type_to_fqn = _build_cmd_type_to_fqn(ir)

    lines: list[str] = ["flowchart LR"]

    # Cluster subgraphs with internal nodes
    for cfqn, cluster in sorted(clusters.items()):
        lines.extend(_render_cluster_subgraph(cfqn, cluster))

    # Edges within clusters
    for cfqn, cluster in sorted(clusters.items()):
        lines.extend(_render_cluster_edges(cfqn, cluster, cmd_type_to_fqn))

    # Event handlers
    lines.extend(_render_event_handler_nodes_and_edges(ir, evt_type_to_fqn))

    # Process managers
    lines.extend(_render_process_managers(ir, evt_type_to_fqn))

    # Projectors
    lines.extend(_render_projectors(ir, evt_type_to_fqn))

    return "\n".join(lines)
