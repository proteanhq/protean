"""EventModeling slice-timeline generator.

Produces Mermaid ``flowchart LR`` output from an IR dict, rendering the
domain as an EventModeling slice timeline. One slice per aggregate cluster
is drawn as a subgraph that reads left to right through up to four kinds of
node (a consumerless or eventless cluster shows fewer):

1. **Command(s)** — the triggers, drawn as parallelograms ``[/.../]``.
2. **Aggregate (state)** — the decider that holds state, a rectangle ``[...]``.
3. **Event(s)** — the cluster's non-fact events, stadiums ``([...])``.
4. **Read models and automations** — the downstream consumers of those
   events. Projectors are read models, drawn as cylinders ``[(...)]``.
   Event handlers and process managers are automations, drawn as hexagons
   ``{{...}}`` so a read model and an automation are told apart at a glance
   and neither is confused with the aggregate box. A process-manager node
   carries its ``start``/``end`` lifecycle, both in the node label and on
   the edge from the triggering event.

The render is derived purely from ``to_ir()`` (clusters, projections,
flows). A consumer attaches to a slice's event when the event's
``__type__`` string is a key in the consumer's ``handlers`` map, so there is
no dependence on the optional, fail-open ``method_edges`` field. This is the
same predicate :mod:`protean.ir.generators.events` uses; the two diverge in
that this view filters fact events and draws a distinct node per matched
event rather than folding ``__type__`` collisions into one edge.

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


def _read_model_node_line(node_id: str, label: str) -> str:
    """Read-model node: a cylinder ``[(...)]``, marking a queryable view."""
    return f"        {node_id}[({mermaid_escape(label)})]"


def _automation_node_line(node_id: str, label: str) -> str:
    """Automation node: a hexagon ``{{...}}``, distinct from the aggregate box."""
    escaped = mermaid_escape(label)
    return f"        {node_id}{{{{{escaped}}}}}"


def _pm_lifecycle_label(pm_fqn: str, handlers: dict[str, Any]) -> str:
    """Annotate a process-manager label with its ``start``/``end`` lifecycle.

    Reads the lifecycle across all of the PM's handlers, so ``FulfillmentPM``
    becomes ``FulfillmentPM (start, end)`` when any handler starts the flow
    and any handler ends it, matching the event-flow generator.
    """
    annotations: list[str] = []
    if any(info.get("start") for info in handlers.values()):
        annotations.append("start")
    if any(info.get("end") for info in handlers.values()):
        annotations.append("end")
    label = short_name(pm_fqn)
    if annotations:
        label = f"{label} ({', '.join(annotations)})"
    return label


def _pm_edge_label(handler_info: dict[str, Any]) -> str:
    """Return the ``start``/``end`` label for the edge into a PM, or ``""``."""
    parts: list[str] = []
    if handler_info.get("start"):
        parts.append("start")
    if handler_info.get("end"):
        parts.append("end")
    return ", ".join(parts)


def _read_models_for(
    ir: dict[str, Any],
    cluster_fqn: str,
    evt_type: str,
) -> list[tuple[str, str]]:
    """Find projectors (read models) that consume an event.

    Returns ``(node_id, node_line)`` pairs for every projector whose
    ``handlers`` map contains *evt_type*, labelled with the projection the
    projector is ``projector_for``. An empty *evt_type* matches nothing: it
    is never a key in any ``handlers`` map, so the membership check below
    skips every projector.
    """
    results: list[tuple[str, str]] = []
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
            node_line = _read_model_node_line(node_id, label)
            results.append((node_id, node_line))

    return results


def _automations_for(
    ir: dict[str, Any],
    cluster_fqn: str,
    evt_type: str,
) -> list[tuple[str, str, str]]:
    """Find event handlers and process managers (automations) for an event.

    Scans event handlers across every cluster and process managers under
    ``flows``, matching by the event ``__type__`` string, so a cross-cluster
    consumer is found too. Returns ``(node_id, node_line, edge_label)``
    triples; *edge_label* is empty for event handlers and carries the
    process-manager ``start``/``end`` lifecycle for the matched event. An
    empty *evt_type* matches nothing: it is never a key in any ``handlers``
    map, so the membership checks below skip every consumer.
    """
    results: list[tuple[str, str, str]] = []
    for _c_fqn, cluster in sorted(ir.get("clusters", {}).items()):
        for eh_fqn, event_handler in sorted(cluster.get("event_handlers", {}).items()):
            if evt_type not in event_handler.get("handlers", {}):
                continue
            node_id = _automation_node_id(cluster_fqn, eh_fqn)
            node_line = _automation_node_line(node_id, short_name(eh_fqn))
            results.append((node_id, node_line, ""))

    process_managers = ir.get("flows", {}).get("process_managers", {})
    for pm_fqn, process_manager in sorted(process_managers.items()):
        handlers = process_manager.get("handlers", {})
        if evt_type not in handlers:
            continue
        node_id = _automation_node_id(cluster_fqn, pm_fqn)
        node_line = _automation_node_line(
            node_id, _pm_lifecycle_label(pm_fqn, handlers)
        )
        edge_label = _pm_edge_label(handlers[evt_type])
        results.append((node_id, node_line, edge_label))

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
        for node_id, node_line, edge_label in _automations_for(
            ir, cluster_fqn, evt_type
        ):
            consumer_nodes[node_id] = node_line
            if edge_label:
                edge_lines.append(
                    f"    {evt_id} -->|{mermaid_escape(edge_label)}| {node_id}"
                )
            else:
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
