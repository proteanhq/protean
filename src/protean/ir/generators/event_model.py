"""EventModeling slice-timeline generator.

Produces Mermaid ``flowchart LR`` output from an IR dict, rendering the
domain as an EventModeling slice timeline. One slice per aggregate cluster
reads left to right across four columns:

1. **Command(s)** — the triggers.
2. **Aggregate (state)** — the decider that holds state.
3. **Event(s)** — the cluster's non-fact events.
4. **Read models / Automations** — the downstream consumers of those events
   (projectors as read models, event handlers and process managers as
   automations).

The render is derived purely from ``to_ir()`` (clusters, projections,
flows). Consumers are matched to a slice's events by the event
``__type__`` string, the same way :mod:`protean.ir.generators.events`
matches downstream consumers, so no dependence on the optional, fail-open
``method_edges`` field.

Usage::

    from protean.ir.generators.event_model import (
        generate_event_model_slice,
        generate_event_model_timeline,
    )

    diagram = generate_event_model_timeline(ir)
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


def _agg_node_id(fqn: str) -> str:
    return f"agg_{sanitize_mermaid_id(fqn)}"


def _evt_node_id(fqn: str) -> str:
    return f"evt_{sanitize_mermaid_id(fqn)}"


def _read_model_node_id(cluster_fqn: str, fqn: str) -> str:
    # Namespaced by cluster so a projector that consumes events from two
    # aggregates renders as its own node in each slice, keeping every slice
    # self-contained instead of leaking a shared node into one subgraph.
    return f"rm_{sanitize_mermaid_id(cluster_fqn)}_{sanitize_mermaid_id(fqn)}"


def _automation_node_id(cluster_fqn: str, fqn: str) -> str:
    return f"auto_{sanitize_mermaid_id(cluster_fqn)}_{sanitize_mermaid_id(fqn)}"


def _read_models_for(
    ir: dict[str, Any],
    cluster_fqn: str,
    evt_type: str,
) -> list[tuple[str, str]]:
    """Find projectors (read models) that consume an event.

    Returns ``(node_id, node_line)`` pairs for every projector whose
    ``handlers`` map contains *evt_type*, labelled with the projection the
    projector is ``projector_for``.
    """
    results: list[tuple[str, str]] = []
    if not evt_type:
        return results

    for _proj_group_fqn, proj_group in sorted(ir.get("projections", {}).items()):
        for proj_fqn, projector in sorted(proj_group.get("projectors", {}).items()):
            if evt_type not in projector.get("handlers", {}):
                continue
            node_id = _read_model_node_id(cluster_fqn, proj_fqn)
            proj_short = short_name(proj_fqn)
            projection_short = short_name(projector.get("projector_for", ""))
            label = proj_short
            if projection_short:
                label = f"{proj_short} → {projection_short}"
            node_line = f"        {node_id}[{mermaid_escape(label)}]"
            results.append((node_id, node_line))

    return results


def _automations_for(
    ir: dict[str, Any],
    cluster_fqn: str,
    evt_type: str,
) -> list[tuple[str, str]]:
    """Find event handlers and process managers (automations) for an event.

    Scans event handlers across every cluster and process managers under
    ``flows``, matching by the event ``__type__`` string exactly as the
    event-flow generator does, so a cross-cluster consumer is found too.
    Returns ``(node_id, node_line)`` pairs.
    """
    results: list[tuple[str, str]] = []
    if not evt_type:
        return results

    for _c_fqn, cluster in sorted(ir.get("clusters", {}).items()):
        for eh_fqn, event_handler in sorted(cluster.get("event_handlers", {}).items()):
            if evt_type not in event_handler.get("handlers", {}):
                continue
            node_id = _automation_node_id(cluster_fqn, eh_fqn)
            node_line = f"        {node_id}[{mermaid_escape(short_name(eh_fqn))}]"
            results.append((node_id, node_line))

    process_managers = ir.get("flows", {}).get("process_managers", {})
    for pm_fqn, process_manager in sorted(process_managers.items()):
        if evt_type not in process_manager.get("handlers", {}):
            continue
        node_id = _automation_node_id(cluster_fqn, pm_fqn)
        node_line = f"        {node_id}[{mermaid_escape(short_name(pm_fqn))}]"
        results.append((node_id, node_line))

    return results


def _render_slice(
    ir: dict[str, Any],
    cluster_fqn: str,
    cluster: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Render one aggregate cluster as a slice subgraph plus its edges.

    Returns ``(subgraph_lines, edge_lines)``. The subgraph holds the
    command, aggregate, event, and consumer nodes; the edges run left to
    right: command -> aggregate -> event -> consumer.
    """
    agg_short = short_name(cluster_fqn)
    subgraph_id = sanitize_mermaid_id(cluster_fqn)
    agg_id = _agg_node_id(cluster_fqn)

    node_lines: list[str] = []
    edge_lines: list[str] = []

    # Commands (parallelogram) -> aggregate
    for cmd_fqn in sorted(cluster.get("commands", {})):
        cmd_id = _cmd_node_id(cmd_fqn)
        node_lines.append(f"        {cmd_id}[/{mermaid_escape(short_name(cmd_fqn))}/]")
        edge_lines.append(f"    {cmd_id} --> {agg_id}")

    # Aggregate (state)
    node_lines.append(f"        {agg_id}[{mermaid_escape(agg_short)}]")

    # Events (stadium) and their consumers, deduped per slice
    consumer_nodes: dict[str, str] = {}
    for evt_fqn, evt in sorted(cluster.get("events", {}).items()):
        if evt.get("is_fact_event"):
            continue
        evt_id = _evt_node_id(evt_fqn)
        node_lines.append(f"        {evt_id}([{mermaid_escape(short_name(evt_fqn))}])")
        edge_lines.append(f"    {agg_id} --> {evt_id}")

        evt_type = evt.get("__type__", "")
        for node_id, node_line in _read_models_for(ir, cluster_fqn, evt_type):
            consumer_nodes[node_id] = node_line
            edge_lines.append(f"    {evt_id} --> {node_id}")
        for node_id, node_line in _automations_for(ir, cluster_fqn, evt_type):
            consumer_nodes[node_id] = node_line
            edge_lines.append(f"    {evt_id} --> {node_id}")

    node_lines.extend(consumer_nodes[node_id] for node_id in sorted(consumer_nodes))

    subgraph_lines: list[str] = [
        f"    subgraph {subgraph_id}[{mermaid_escape(agg_short)}]",
        *node_lines,
        "    end",
    ]
    return subgraph_lines, edge_lines


def generate_event_model_slice(ir: dict[str, Any], cluster_fqn: str) -> str:
    """Generate a Mermaid ``flowchart LR`` for a single aggregate's slice.

    Renders command -> aggregate -> event -> consumer for the given
    cluster. Returns the bare ``flowchart LR`` sentinel when the cluster is
    absent.

    Args:
        ir: The full IR dict.
        cluster_fqn: FQN of the cluster to render.

    Returns:
        A string containing the Mermaid ``flowchart LR`` source.
    """
    cluster = ir.get("clusters", {}).get(cluster_fqn)
    if not cluster:
        return "flowchart LR"

    subgraph_lines, edge_lines = _render_slice(ir, cluster_fqn, cluster)
    lines: list[str] = ["flowchart LR", *subgraph_lines, *edge_lines]
    return "\n".join(lines)


def generate_event_model_timeline(ir: dict[str, Any]) -> str:
    """Generate a Mermaid ``flowchart LR`` for the whole event-model timeline.

    Renders one slice per aggregate cluster, in sorted order, each slice a
    subgraph of command -> aggregate -> event -> consumer. Returns the bare
    ``flowchart LR`` sentinel when there are no clusters.

    Args:
        ir: The full IR dict.

    Returns:
        A string containing the Mermaid ``flowchart LR`` source.
    """
    clusters = ir.get("clusters", {})
    if not clusters:
        return "flowchart LR"

    lines: list[str] = ["flowchart LR"]
    all_edges: list[str] = []
    for cluster_fqn, cluster in sorted(clusters.items()):
        subgraph_lines, edge_lines = _render_slice(ir, cluster_fqn, cluster)
        lines.extend(subgraph_lines)
        all_edges.extend(edge_lines)

    lines.extend(all_edges)
    return "\n".join(lines)
