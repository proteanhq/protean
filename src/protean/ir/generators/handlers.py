"""Handler wiring diagram generator.

Produces Mermaid ``flowchart TD`` output from an IR dict, organised by
handler type.  Each handler category is rendered as a subgraph with
incoming edges from the commands or events it handles.

Groups:

- **Command Handlers** — commands → handler → aggregate
- **Event Handlers** — events → handler
- **Process Managers** — events → PM (with lifecycle labels)
- **Projectors** — events → projector (with projection target label)
- **Subscribers** — standalone nodes labelled with their broker stream

Usage::

    from protean.ir.generators.handlers import generate_handler_wiring_diagram

    diagram = generate_handler_wiring_diagram(ir)
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import (
    build_cmd_type_to_fqn,
    build_evt_type_to_fqn,
    mermaid_escape,
    sanitize_mermaid_id,
    short_name,
)


# ---------------------------------------------------------------------------
# Node ID helpers — prefixed to avoid collisions across handler types
# ---------------------------------------------------------------------------


def _cmd_node_id(fqn: str) -> str:
    return f"cmd_{sanitize_mermaid_id(fqn)}"


def _evt_node_id(fqn: str) -> str:
    return f"evt_{sanitize_mermaid_id(fqn)}"


def _agg_node_id(fqn: str) -> str:
    return f"agg_{sanitize_mermaid_id(fqn)}"


def _ch_node_id(fqn: str) -> str:
    return f"ch_{sanitize_mermaid_id(fqn)}"


def _eh_node_id(fqn: str) -> str:
    return f"eh_{sanitize_mermaid_id(fqn)}"


def _pm_node_id(fqn: str) -> str:
    return f"pm_{sanitize_mermaid_id(fqn)}"


def _proj_node_id(fqn: str) -> str:
    return f"proj_{sanitize_mermaid_id(fqn)}"


def _sub_node_id(fqn: str) -> str:
    return f"sub_{sanitize_mermaid_id(fqn)}"


# ---------------------------------------------------------------------------
# Subgraph renderers
# ---------------------------------------------------------------------------


def _render_command_handlers(
    ir: dict[str, Any],
    cmd_type_to_fqn: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Render Command Handler subgraph and external edges.

    Returns ``(subgraph_lines, edge_lines)`` so the caller can place edges
    after all subgraphs.
    """
    nodes: list[str] = []
    edges: list[str] = []

    for cluster_fqn, cluster in sorted(ir.get("clusters", {}).items()):
        for ch_fqn, ch in sorted(cluster.get("command_handlers", {}).items()):
            ch_id = _ch_node_id(ch_fqn)
            ch_short = short_name(ch_fqn)
            nodes.append(f"        {ch_id}[{mermaid_escape(ch_short)}]")

            # commands → handler
            for cmd_type in sorted(ch.get("handlers", {}).keys()):
                cmd_fqn = cmd_type_to_fqn.get(cmd_type, "")
                if cmd_fqn:
                    cmd_id = _cmd_node_id(cmd_fqn)
                    cmd_short = short_name(cmd_fqn)
                    edges.append(
                        f"    {cmd_id}[/{mermaid_escape(cmd_short)}/] --> {ch_id}"
                    )

            # handler → aggregate
            agg_id = _agg_node_id(cluster_fqn)
            agg_short = short_name(cluster_fqn)
            edges.append(f"    {ch_id} --> {agg_id}[{mermaid_escape(agg_short)}]")

    if not nodes:
        return [], []

    subgraph: list[str] = [
        '    subgraph command_handlers["Command Handlers"]',
        *nodes,
        "    end",
    ]
    return subgraph, edges


def _render_event_handlers(
    ir: dict[str, Any],
    evt_type_to_fqn: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Render Event Handler subgraph and external edges."""
    nodes: list[str] = []
    edges: list[str] = []

    for _cluster_fqn, cluster in sorted(ir.get("clusters", {}).items()):
        for eh_fqn, eh in sorted(cluster.get("event_handlers", {}).items()):
            eh_id = _eh_node_id(eh_fqn)
            eh_short = short_name(eh_fqn)
            nodes.append(f"        {eh_id}[{mermaid_escape(eh_short)}]")

            for evt_type in sorted(eh.get("handlers", {}).keys()):
                evt_fqn = evt_type_to_fqn.get(evt_type, "")
                if evt_fqn:
                    evt_id = _evt_node_id(evt_fqn)
                    evt_short = short_name(evt_fqn)
                    edges.append(
                        f"    {evt_id}([{mermaid_escape(evt_short)}]) --> {eh_id}"
                    )

    if not nodes:
        return [], []

    subgraph: list[str] = [
        '    subgraph event_handlers["Event Handlers"]',
        *nodes,
        "    end",
    ]
    return subgraph, edges


def _render_process_managers(
    ir: dict[str, Any],
    evt_type_to_fqn: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Render Process Manager subgraph and external edges."""
    nodes: list[str] = []
    edges: list[str] = []
    pms = ir.get("flows", {}).get("process_managers", {})

    for pm_fqn, pm in sorted(pms.items()):
        pm_id = _pm_node_id(pm_fqn)
        pm_short = short_name(pm_fqn)

        # Lifecycle annotations on node label
        lifecycle: list[str] = []
        for _evt_type, handler_info in sorted(pm.get("handlers", {}).items()):
            if handler_info.get("start"):
                lifecycle.append("start")
                break
        for _evt_type, handler_info in sorted(pm.get("handlers", {}).items()):
            if handler_info.get("end"):
                lifecycle.append("end")
                break

        label = pm_short
        if lifecycle:
            label = f"{pm_short} ({', '.join(lifecycle)})"

        nodes.append(f"        {pm_id}[{mermaid_escape(label)}]")

        # events → PM with lifecycle edge labels
        for evt_type in sorted(pm.get("handlers", {}).keys()):
            evt_fqn = evt_type_to_fqn.get(evt_type, "")
            if evt_fqn:
                evt_id = _evt_node_id(evt_fqn)
                evt_short = short_name(evt_fqn)
                handler_info = pm["handlers"][evt_type]

                edge_labels: list[str] = []
                if handler_info.get("start"):
                    edge_labels.append("start")
                if handler_info.get("end"):
                    edge_labels.append("end")

                if edge_labels:
                    edge_label = ", ".join(edge_labels)
                    edges.append(
                        f"    {evt_id}([{mermaid_escape(evt_short)}])"
                        f" -->|{mermaid_escape(edge_label)}| {pm_id}"
                    )
                else:
                    edges.append(
                        f"    {evt_id}([{mermaid_escape(evt_short)}]) --> {pm_id}"
                    )

    if not nodes:
        return [], []

    subgraph: list[str] = [
        '    subgraph process_managers["Process Managers"]',
        *nodes,
        "    end",
    ]
    return subgraph, edges


def _render_projectors(
    ir: dict[str, Any],
    evt_type_to_fqn: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Render Projector subgraph and external edges."""
    nodes: list[str] = []
    edges: list[str] = []

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
                label = f"{proj_short} \u2192 {projection_short}"

            nodes.append(f"        {proj_id}[{mermaid_escape(label)}]")

            for evt_type in sorted(projector.get("handlers", {}).keys()):
                evt_fqn = evt_type_to_fqn.get(evt_type, "")
                if evt_fqn:
                    evt_id = _evt_node_id(evt_fqn)
                    evt_short = short_name(evt_fqn)
                    edges.append(
                        f"    {evt_id}([{mermaid_escape(evt_short)}]) --> {proj_id}"
                    )

    if not nodes:
        return [], []

    subgraph: list[str] = [
        '    subgraph projectors["Projectors"]',
        *nodes,
        "    end",
    ]
    return subgraph, edges


def _render_subscribers(ir: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Render Subscriber subgraph (no external edges — streams are labels)."""
    nodes: list[str] = []
    subscribers = ir.get("flows", {}).get("subscribers", {})

    for sub_fqn, sub in sorted(subscribers.items()):
        sub_id = _sub_node_id(sub_fqn)
        sub_short = short_name(sub_fqn)
        stream = sub.get("stream", "")

        label = sub_short
        if stream:
            label = f"{sub_short}\\nstream: {stream}"

        nodes.append(f"        {sub_id}[{mermaid_escape(label)}]")

    if not nodes:
        return [], []

    subgraph: list[str] = [
        '    subgraph subscribers["Subscribers"]',
        *nodes,
        "    end",
    ]
    return subgraph, []


# ---------------------------------------------------------------------------
# Per-category public generators (used for split Markdown output)
# ---------------------------------------------------------------------------


def _assemble_flowchart(subgraph: list[str], edges: list[str]) -> str:
    """Wrap subgraph + edges into a complete ``flowchart TD``."""
    if not subgraph:
        return "flowchart TD"
    lines: list[str] = ["flowchart TD", *subgraph]
    lines.extend(edges)
    return "\n".join(lines)


def generate_command_handler_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart TD`` for command handlers only."""
    cmd_type_to_fqn = build_cmd_type_to_fqn(ir)
    subgraph, edges = _render_command_handlers(ir, cmd_type_to_fqn)
    return _assemble_flowchart(subgraph, edges)


def generate_cluster_command_handler_diagram(
    ir: dict[str, Any], cluster_fqn: str
) -> str:
    """Generate a Mermaid ``flowchart LR`` for one cluster's command handlers."""
    clusters = ir.get("clusters", {})
    cluster = clusters.get(cluster_fqn)
    if not cluster or not cluster.get("command_handlers"):
        return "flowchart LR"

    single_ir: dict[str, Any] = {
        "clusters": {cluster_fqn: cluster},
        "flows": ir.get("flows", {}),
        "projections": ir.get("projections", {}),
    }
    cmd_type_to_fqn = build_cmd_type_to_fqn(ir)
    subgraph, edges = _render_command_handlers(single_ir, cmd_type_to_fqn)
    if not subgraph:
        return "flowchart LR"
    lines: list[str] = ["flowchart LR", *subgraph]
    lines.extend(edges)
    return "\n".join(lines)


def generate_event_handler_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart TD`` for event handlers only."""
    evt_type_to_fqn = build_evt_type_to_fqn(ir)
    subgraph, edges = _render_event_handlers(ir, evt_type_to_fqn)
    return _assemble_flowchart(subgraph, edges)


def generate_process_manager_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart TD`` for process managers only."""
    evt_type_to_fqn = build_evt_type_to_fqn(ir)
    subgraph, edges = _render_process_managers(ir, evt_type_to_fqn)
    return _assemble_flowchart(subgraph, edges)


def generate_projector_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart TD`` for projectors only."""
    evt_type_to_fqn = build_evt_type_to_fqn(ir)
    subgraph, edges = _render_projectors(ir, evt_type_to_fqn)
    return _assemble_flowchart(subgraph, edges)


def generate_single_projector_diagram(ir: dict[str, Any], projection_fqn: str) -> str:
    """Generate a Mermaid ``flowchart LR`` for one projector."""
    projections = ir.get("projections", {})
    proj_group = projections.get(projection_fqn)
    if not proj_group or not proj_group.get("projectors"):
        return "flowchart LR"

    single_ir: dict[str, Any] = {
        "clusters": ir.get("clusters", {}),
        "flows": ir.get("flows", {}),
        "projections": {projection_fqn: proj_group},
    }
    evt_type_to_fqn = build_evt_type_to_fqn(ir)
    subgraph, edges = _render_projectors(single_ir, evt_type_to_fqn)
    if not subgraph:
        return "flowchart LR"
    lines: list[str] = ["flowchart LR", *subgraph]
    lines.extend(edges)
    return "\n".join(lines)


def generate_subscriber_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart TD`` for subscribers only."""
    subgraph, edges = _render_subscribers(ir)
    return _assemble_flowchart(subgraph, edges)


# ---------------------------------------------------------------------------
# Combined public entry point (used for raw Mermaid output)
# ---------------------------------------------------------------------------


def generate_handler_wiring_diagram(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart TD`` showing handler wiring.

    The diagram groups handlers by type, with incoming edges from the
    commands or events they consume.

    Args:
        ir: The full IR dict.

    Returns:
        A string containing the Mermaid ``flowchart TD`` source.
    """
    clusters = ir.get("clusters", {})
    flows = ir.get("flows", {})
    projections = ir.get("projections", {})

    if not clusters and not flows and not projections:
        return "flowchart TD"

    cmd_type_to_fqn = build_cmd_type_to_fqn(ir)
    evt_type_to_fqn = build_evt_type_to_fqn(ir)

    lines: list[str] = ["flowchart TD"]
    all_edges: list[str] = []

    # Render each handler group
    for renderer in (
        lambda: _render_command_handlers(ir, cmd_type_to_fqn),
        lambda: _render_event_handlers(ir, evt_type_to_fqn),
        lambda: _render_process_managers(ir, evt_type_to_fqn),
        lambda: _render_projectors(ir, evt_type_to_fqn),
        lambda: _render_subscribers(ir),
    ):
        subgraph, edges = renderer()
        if subgraph:
            lines.extend(subgraph)
        all_edges.extend(edges)

    # Edges after all subgraphs (Mermaid best practice)
    lines.extend(all_edges)

    return "\n".join(lines)
