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
        generate_event_model_sections,
        generate_event_model_slice,
        generate_event_model_timeline,
    )

    diagram = generate_event_model_timeline(ir)

    # Markdown: one section per slice, consumer indexes built once.
    sections = generate_event_model_sections(ir, annotations)
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

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


def _read_model_index(ir: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """Index projectors (read models) by the event ``__type__`` they consume.

    Maps each event type to ``(projector_fqn, label)`` pairs, where the label
    names the projection the projector is ``projector_for``. Built once per
    render so a slice looks a consumer up instead of rescanning every
    projection for every event.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    for _proj_group_fqn, proj_group in sorted(ir.get("projections", {}).items()):
        for proj_fqn, projector in sorted(proj_group.get("projectors", {}).items()):
            proj_short = short_name(proj_fqn)
            projection_short = short_name(projector.get("projector_for", ""))
            label = proj_short
            if projection_short:
                label = f"{proj_short} → {projection_short}"
            for evt_type in projector.get("handlers", {}):
                index.setdefault(evt_type, []).append((proj_fqn, label))

    return index


def _automation_index(ir: dict[str, Any]) -> dict[str, list[tuple[str, str, str]]]:
    """Index event handlers and process managers (automations) by event type.

    Covers event handlers across every cluster and process managers under
    ``flows``, so a cross-cluster consumer is indexed too. Maps each event
    type to ``(consumer_fqn, label, edge_label)`` triples; *edge_label* is
    empty for event handlers and carries the process-manager ``start``/``end``
    lifecycle for that event. Built once per render, like
    :func:`_read_model_index`.
    """
    index: dict[str, list[tuple[str, str, str]]] = {}
    for _c_fqn, cluster in sorted(ir.get("clusters", {}).items()):
        for eh_fqn, event_handler in sorted(cluster.get("event_handlers", {}).items()):
            for evt_type in event_handler.get("handlers", {}):
                index.setdefault(evt_type, []).append((eh_fqn, short_name(eh_fqn), ""))

    process_managers = ir.get("flows", {}).get("process_managers", {})
    for pm_fqn, process_manager in sorted(process_managers.items()):
        handlers = process_manager.get("handlers", {})
        label = _pm_lifecycle_label(pm_fqn, handlers)
        for evt_type, handler_info in handlers.items():
            index.setdefault(evt_type, []).append(
                (pm_fqn, label, _pm_edge_label(handler_info))
            )

    return index


def _render_slice(
    read_models: dict[str, list[tuple[str, str]]],
    automations: dict[str, list[tuple[str, str, str]]],
    cluster_fqn: str,
    cluster: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Render one aggregate cluster as a slice subgraph plus its edges.

    Returns ``(subgraph_lines, edge_lines)``. The subgraph holds the
    command, aggregate, event, and consumer nodes; the edges run left to
    right: command -> aggregate -> event -> consumer.

    *read_models* and *automations* are the shared indexes from
    :func:`_read_model_index` and :func:`_automation_index`, keyed by event
    ``__type__``. Consumer node ids are namespaced by *cluster_fqn* here, so
    the indexes stay slice-independent and are built once for the whole
    render.
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

        # An empty ``__type__`` matches nothing: it is never a key in any
        # ``handlers`` map, so it is never a key in either index.
        evt_type = evt.get("__type__", "")
        for proj_fqn, label in read_models.get(evt_type, []):
            node_id = _read_model_node_id(cluster_fqn, proj_fqn)
            consumer_nodes[node_id] = _read_model_node_line(node_id, label)
            edge_lines.append(f"    {evt_id} --> {node_id}")
        for consumer_fqn, label, edge_label in automations.get(evt_type, []):
            node_id = _automation_node_id(cluster_fqn, consumer_fqn)
            consumer_nodes[node_id] = _automation_node_line(node_id, label)
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


def _slice_diagram(
    read_models: dict[str, list[tuple[str, str]]],
    automations: dict[str, list[tuple[str, str, str]]],
    cluster_fqn: str,
    cluster: dict[str, Any],
) -> str:
    """Render one cluster's slice as a standalone ``flowchart LR``."""
    subgraph_lines, edge_lines = _render_slice(
        read_models, automations, cluster_fqn, cluster
    )
    return "\n".join(["flowchart LR", *subgraph_lines, *edge_lines])


def generate_slice_gwt(ir: dict[str, Any], cluster_fqn: str) -> str:
    """Render the structural Given-When-Then for one aggregate slice.

    Returns a Markdown blockquote (``> **Given** ...`` lines) that leads a
    slice with a structural Given-When-Then before the diagram. The GWT is
    derived structurally from the IR, which is always available:

    - **Given:** the aggregate the slice is about. The IR encodes no temporal
      order between events, so there is no reliable list of prior events to
      show yet; the honest structural Given is the aggregate. This is where
      later scenario metadata would enrich the line.
    - **When:** the cluster's commands (the triggers), short names, ordered by
      FQN. Omitted when the cluster has no commands.
    - **Then:** the cluster's non-fact events (the results), short names,
      ordered by FQN. Fact events are filtered with the same predicate the
      diagram uses, so GWT and diagram agree on which events exist. Omitted
      when the cluster raises no non-fact events.

    Both lines list one entry per FQN, matching the diagram, which draws one
    node per FQN. Two elements from different modules that share a short name
    are listed twice rather than collapsed, so the two views never disagree.

    This is slice-level pairing: one GWT per slice. A one-command /
    one-event slice reads ``When PlaceOrder`` / ``Then OrderPlaced``. A
    multi-command / multi-event slice lists the commands on the When line and
    the events on the Then line, which is coarse but honest. Precise
    per-command-to-event pairing (via the command-handler ``invokes`` to
    aggregate ``raises`` chain) is deliberately left out of this version: it
    would depend on the optional, fail-open ``method_edges`` field this
    generator avoids, and it is part of the same "enrich later" growth path
    as scenario metadata.

    Args:
        ir: The full IR dict.
        cluster_fqn: FQN of the cluster to render.

    Returns:
        The Markdown GWT block for the cluster, or ``""`` when the cluster is
        absent from the IR.
    """
    cluster = ir.get("clusters", {}).get(cluster_fqn)
    if cluster is None:
        return ""

    lines: list[str] = [f"> **Given** {short_name(cluster_fqn)}"]

    # Sorted by FQN and not deduped by short name: the diagram draws one node
    # per FQN, so two elements from different modules that share a short name
    # must appear twice here too, or the GWT would disagree with the diagram.
    commands = [short_name(cmd_fqn) for cmd_fqn in sorted(cluster.get("commands", {}))]
    if commands:
        lines.append(f"> **When** {', '.join(commands)}")

    events = [
        short_name(evt_fqn)
        for evt_fqn, evt in sorted(cluster.get("events", {}).items())
        if not evt.get("is_fact_event")
    ]
    if events:
        lines.append(f"> **Then** {', '.join(events)}")

    return "\n".join(lines)


class _DrawnConsumers(NamedTuple):
    """Drawn consumer nodes, split by the kind of node the diagram draws.

    ``read_models`` holds the projectors (cylinders) and ``automations`` the
    event handlers and process managers (hexagons). The two are kept apart
    because the diff names them differently: a projector is reported under the
    read model it feeds, an automation under its own name.

    Each maps a consumer FQN to the label the diagram draws that node with, so
    a caller can tell a node that moved or was relabelled from one that stayed
    put. The label is the one :func:`_render_slice` writes: ``Projector →
    Projection`` for a projector, the short name for an event handler, and the
    ``start``/``end`` lifecycle annotation for a process manager.
    """

    read_models: dict[str, str]
    automations: dict[str, str]


def _slice_consumers(
    read_models: dict[str, list[tuple[str, str]]],
    automations: dict[str, list[tuple[str, str, str]]],
    cluster: dict[str, Any],
) -> _DrawnConsumers:
    """Return every consumer drawn in a cluster's slice, mapped to its label.

    A consumer (projector, event handler, or process manager) is drawn in
    the slice when it handles one of the cluster's non-fact events. Uses the
    same shared indexes and the same fact-event / empty-``__type__`` filters
    as :func:`_render_slice`, so the match set agrees with the diagram.
    """
    projector_labels: dict[str, str] = {}
    automation_labels: dict[str, str] = {}
    for evt in cluster.get("events", {}).values():
        if evt.get("is_fact_event"):
            continue
        evt_type = evt.get("__type__", "")
        if not evt_type:
            continue
        projector_labels.update(read_models.get(evt_type, []))
        automation_labels.update(
            (consumer_fqn, label)
            for consumer_fqn, label, _edge in automations.get(evt_type, [])
        )
    return _DrawnConsumers(projector_labels, automation_labels)


def _cluster_target_fqns(
    read_models: dict[str, list[tuple[str, str]]],
    automations: dict[str, list[tuple[str, str, str]]],
    cluster_fqn: str,
    cluster: dict[str, Any],
) -> set[str]:
    """Return every element FQN a note can attach to in one cluster's slice.

    That is the aggregate, its commands, its non-fact events, and the
    consumers drawn from those events. This is exactly the set of nodes the
    slice draws, so a note keyed by any of them renders in the slice, and a
    note keyed by anything else (including a fact event, which the model
    filters out) is reported unmatched.
    """
    fqns: set[str] = {cluster_fqn}
    if cluster:
        fqns.update(cluster.get("commands", {}))
        fqns.update(
            evt_fqn
            for evt_fqn, evt in cluster.get("events", {}).items()
            if not evt.get("is_fact_event")
        )
        consumers = _slice_consumers(read_models, automations, cluster)
        fqns.update(consumers.read_models, consumers.automations)
    return fqns


def slice_annotation_targets(ir: dict[str, Any], cluster_fqn: str) -> set[str]:
    """Return the element FQNs a note can attach to in *cluster_fqn*'s slice.

    Returns an empty set when the cluster is absent from the IR. An empty
    cluster mapping is present, not absent, so its aggregate FQN is still a
    valid target (the slice still draws the aggregate box).

    Args:
        ir: The full IR dict.
        cluster_fqn: FQN of the cluster to inspect.

    Returns:
        The set of element FQNs drawn in that slice.
    """
    cluster = ir.get("clusters", {}).get(cluster_fqn)
    if cluster is None:
        return set()
    return _cluster_target_fqns(
        _read_model_index(ir), _automation_index(ir), cluster_fqn, cluster
    )


def element_fqns(ir: dict[str, Any]) -> set[str]:
    """Return the FQN of every element the event model draws, across all slices.

    The union of :func:`slice_annotation_targets` over every cluster, built
    with the consumer indexes assembled once for the whole IR. This is the
    match set for annotations: a key in this set attaches to a slice, a key
    outside it is unmatched.

    Args:
        ir: The full IR dict.

    Returns:
        The set of every drawn element FQN.
    """
    read_models = _read_model_index(ir)
    automations = _automation_index(ir)
    fqns: set[str] = set()
    for cluster_fqn, cluster in ir.get("clusters", {}).items():
        fqns |= _cluster_target_fqns(
            read_models, automations, cluster_fqn, cluster or {}
        )
    return fqns


def unmatched_annotations(
    ir: dict[str, Any], annotations: dict[str, dict[str, Any]]
) -> list[str]:
    """Return the sorted annotation keys that match no element in the model.

    An unmatched key is a note orphaned by a rename or a typo. It is reported,
    never dropped in silence (ADR-0032). Returns an empty list when there are
    no annotations or every key matches.

    Args:
        ir: The full IR dict.
        annotations: Mapping of element FQN to its annotation entry.

    Returns:
        The sorted list of keys present in *annotations* but not in the model.
    """
    if not annotations:
        return []
    matched = element_fqns(ir)
    return sorted(fqn for fqn in annotations if fqn not in matched)


def _blockquote_lines(label: str, text: str) -> list[str]:
    """Render ``**label:** text`` as blockquote lines, one per input line.

    Every line of *text* is ``> ``-prefixed so a multi-line value cannot break
    out of the quote. A blank continuation line becomes a bare ``>``.
    """
    parts = text.split("\n")
    lines = [f"> **{label}:** {parts[0]}".rstrip()]
    lines.extend(f"> {extra}".rstrip() if extra.strip() else ">" for extra in parts[1:])
    return lines


def _annotation_block(entry: dict[str, Any]) -> str:
    """Render one annotation entry as a Markdown blockquote.

    The ``note`` leads (``> **Note:** ...``). An ``owner``, when present,
    follows as a second paragraph (``> **Owner:** ...``). Both carry multi-line
    text safely: every line is ``> ``-prefixed, so a value with embedded
    newlines stays inside the quote instead of forging a heading below it.
    """
    lines = _blockquote_lines("Note", str(entry.get("note", "")).strip())

    owner = str(entry.get("owner", "")).strip()
    if owner:
        lines.append(">")
        lines.extend(_blockquote_lines("Owner", owner))

    return "\n".join(lines)


def _render_annotations(
    targets: set[str], annotations: dict[str, dict[str, Any]]
) -> str:
    """Render the annotations keyed to *targets*, in sorted FQN order."""
    if not annotations:
        return ""
    blocks = [
        _annotation_block(annotations[fqn])
        for fqn in sorted(targets)
        if fqn in annotations
    ]
    return "\n\n".join(blocks)


def generate_slice_annotations(
    ir: dict[str, Any],
    cluster_fqn: str,
    annotations: dict[str, dict[str, Any]],
) -> str:
    """Render the human notes attached to one aggregate slice.

    Returns the Markdown for every annotation whose FQN is drawn in the
    slice, in sorted FQN order, or ``""`` when the slice carries no notes.
    An empty *annotations* mapping renders nothing, which keeps the no-file
    baseline byte-identical to the pre-annotation render.

    Renders one slice, so it builds the consumer indexes itself. To render
    every slice, use :func:`generate_event_model_sections`, which builds them
    once for the whole model.

    Args:
        ir: The full IR dict.
        cluster_fqn: FQN of the cluster whose slice is being rendered.
        annotations: Mapping of element FQN to its annotation entry.

    Returns:
        The Markdown note block(s) for the slice, or ``""``.
    """
    if not annotations:
        return ""
    return _render_annotations(slice_annotation_targets(ir, cluster_fqn), annotations)


def _inline_code(text: str) -> str:
    """Wrap *text* in a Markdown code span that survives any content.

    The fence is one backtick longer than the longest backtick run inside
    *text*, which is how CommonMark keeps a code span open, so a key carrying
    backticks cannot terminate the span early. Text that starts or ends with
    a backtick is padded with a space, which the renderer strips back off.

    Args:
        text: The literal text to show as code.

    Returns:
        The code span.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if not text or text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def render_unmatched_annotations(keys: list[str]) -> str:
    """Render the unmatched-annotation report from a list of *keys*.

    Returns ``""`` for an empty list so callers append nothing when every
    annotation matched. The keys are shown in a Markdown list under an
    ``## Unmatched annotations`` heading, each on its own line. Newlines in a
    key (a valid but pathological TOML key) are collapsed to spaces so a key
    cannot break the list or forge a heading below it, and backticks in a key
    are held inside a longer fence so they cannot cut the code span short.

    Args:
        keys: The sorted unmatched annotation keys.

    Returns:
        The Markdown report, or ``""`` when *keys* is empty.
    """
    if not keys:
        return ""
    lines = [
        "## Unmatched annotations",
        "",
        "These annotation keys match no element in the model:",
        "",
    ]
    lines.extend(f"- {_inline_code(' '.join(key.splitlines()))}" for key in keys)
    return "\n".join(lines)


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
    if cluster is None:
        return "flowchart LR"

    return _slice_diagram(
        _read_model_index(ir), _automation_index(ir), cluster_fqn, cluster
    )


class EventModelSection(NamedTuple):
    """One rendered slice of the event model, ready to place in a document.

    ``cluster_fqn`` names the aggregate the slice is about, ``gwt`` and
    ``notes`` are the Markdown blocks that lead it (``notes`` is ``""`` when
    the slice carries none), and ``diagram`` is the bare Mermaid source, with
    no fence around it, so a caller can wrap it however it likes.
    """

    cluster_fqn: str
    gwt: str
    notes: str
    diagram: str


def generate_event_model_sections(
    ir: dict[str, Any],
    annotations: dict[str, dict[str, Any]],
) -> list[EventModelSection]:
    """Render every aggregate slice, in sorted cluster order.

    This is the whole-document counterpart to the per-slice functions. It
    builds the projector and automation indexes once and reuses them for every
    slice, so a render costs one pass over the projections and flows rather
    than one per slice. Calling :func:`generate_event_model_slice` and
    :func:`generate_slice_annotations` in a loop rebuilds both indexes on each
    call; prefer this when rendering the full model.

    Args:
        ir: The full IR dict.
        annotations: Mapping of element FQN to its annotation entry.

    Returns:
        One :class:`EventModelSection` per cluster, sorted by cluster FQN.
    """
    read_models = _read_model_index(ir)
    automations = _automation_index(ir)

    sections: list[EventModelSection] = []
    for cluster_fqn, cluster in sorted(ir.get("clusters", {}).items()):
        targets = _cluster_target_fqns(read_models, automations, cluster_fqn, cluster)
        sections.append(
            EventModelSection(
                cluster_fqn=cluster_fqn,
                gwt=generate_slice_gwt(ir, cluster_fqn),
                notes=_render_annotations(targets, annotations),
                diagram=_slice_diagram(read_models, automations, cluster_fqn, cluster),
            )
        )
    return sections


# ------------------------------------------------------------------
# Diff rendering — an IR diff in slice vocabulary
# ------------------------------------------------------------------


def _summary_name(info: dict[str, Any], fqn: str) -> str:
    """Name an element from its diff summary, falling back to the short FQN.

    ``_element_summary`` (``ir/diff.py``) sets ``name`` to the aggregate name
    for a cluster and the projection name for a projection group. A removed
    element is absent from the right snapshot, so its name can only come from
    the summary; when the summary carries none, the short FQN is the honest
    fallback.
    """
    name = info.get("name")
    return name if name else short_name(fqn)


def _field_change_phrases(fields_diff: dict[str, Any]) -> list[str]:
    """Render a ``_diff_fields`` result as ``field <name> added/removed/changed``.

    Reuses the ``{added, removed, changed}`` shape ``_diff_fields`` produces, so
    the model diff names the same fields the IR diff does.
    """
    phrases: list[str] = []
    phrases.extend(
        f"field {name} added" for name in sorted(fields_diff.get("added", {}))
    )
    phrases.extend(
        f"field {name} removed" for name in sorted(fields_diff.get("removed", {}))
    )
    phrases.extend(
        f"field {name} changed" for name in sorted(fields_diff.get("changed", {}))
    )
    return phrases


# ``method_edges`` is the optional, fail-open raise/invoke derivation the event
# model generators deliberately do not read (see :func:`generate_slice_gwt`), so
# a delta confined to it is not a model change.
_UNDRAWN_DELTA_KEYS = frozenset({"method_edges"})


def _handler_lifecycle(handler_entry: Any) -> tuple[bool, bool]:
    """The ``(start, end)`` lifecycle one handler-map entry contributes.

    A process-manager entry is a dict carrying ``start``/``end``; an event
    handler or projector entry is a list of method names and carries none. The
    event model reads a consumer's routing keys and, for a process manager,
    this lifecycle. It never reads the mapped method names.
    """
    if isinstance(handler_entry, dict):
        return bool(handler_entry.get("start")), bool(handler_entry.get("end"))
    return False, False


class _DrawnEventTypes(NamedTuple):
    """The event ``__type__`` strings each snapshot's diagram draws.

    A routing key only moves a node when it names an event some slice draws, so
    a handler-map change is judged against the side it lands on: an added key
    against the right snapshot, a removed key against the left.
    """

    left: frozenset[str]
    right: frozenset[str]


def _drawn_event_types(ir: dict[str, Any]) -> frozenset[str]:
    """Every event ``__type__`` the model draws anywhere in *ir*.

    Applies the filters :func:`_render_slice` applies: a fact event is not
    drawn, and an empty ``__type__`` is a key in no handler map.
    """
    types: set[str] = set()
    for cluster in ir.get("clusters", {}).values():
        for evt in cluster.get("events", {}).values():
            if evt.get("is_fact_event"):
                continue
            evt_type = evt.get("__type__", "")
            if evt_type:
                types.add(evt_type)
    return frozenset(types)


def _handlers_delta_is_drawn(
    handlers_delta: dict[str, Any], drawn_types: _DrawnEventTypes
) -> bool:
    """Whether a ``handlers`` diff moves a node the event model draws.

    A consumer attaches to a slice by the event ``__type__`` strings that key
    its ``handlers`` map, so gaining or losing a routing key moves its node, but
    only when that key names an event the diagram draws. A route to a fact
    event, or to an event no cluster raises, draws nothing, so adding or
    dropping it leaves the slice as it was. Each key is checked against the side
    it lands on: an added key against the right snapshot, a removed key against
    the left. A same-key change is drawn only when a process manager's
    ``start``/``end`` lifecycle flips on a drawn route; renaming the mapped
    handler method leaves the diagram unchanged. A lifecycle flip on an undrawn
    route still changes the PM's node label, which is why
    :func:`_consumer_transitions` compares node labels as well as this delta.
    """
    if any(
        evt_type in drawn_types.right for evt_type in handlers_delta.get("added", {})
    ):
        return True
    if any(
        evt_type in drawn_types.left for evt_type in handlers_delta.get("removed", {})
    ):
        return True
    return any(
        (evt_type in drawn_types.left or evt_type in drawn_types.right)
        and _handler_lifecycle(entry.get("left"))
        != _handler_lifecycle(entry.get("right"))
        for evt_type, entry in handlers_delta.get("changed", {}).items()
    )


def _delta_is_drawn(delta: dict[str, Any], drawn_types: _DrawnEventTypes) -> bool:
    """Whether *delta* touches anything the event model reads.

    ``method_edges`` is never read. A ``handlers`` delta counts only when it
    changes a drawn routing key or a process manager's lifecycle (see
    :func:`_handlers_delta_is_drawn`), so a bare method rename does not, and
    neither does a route to an event no slice draws. Every other key is treated
    as drawn.
    """
    for key, value in delta.items():
        if key in _UNDRAWN_DELTA_KEYS:
            continue
        if key == "handlers":
            if _handlers_delta_is_drawn(value, drawn_types):
                return True
            continue
        return True
    return False


def _element_change_phrases(
    delta: dict[str, Any], drawn_types: _DrawnEventTypes
) -> list[str]:
    """Render one drawn participant's ``_diff_element`` delta as phrases.

    Names the fields when fields moved, because that is the detail worth
    reading. A delta that touches anything else the element carries (options,
    invariants, routing-key changes, scalar attributes such as ``__type__``)
    still changes a participant the model draws, so it renders as a bare
    ``changed`` rather than disappearing into ``No model changes.``. Named
    fields already say the participant changed, so the bare phrase is only added
    when nothing else was rendered.

    A ``handlers`` delta is judged by what the diagram draws: a drawn
    routing-key change or a process manager's lifecycle flip counts, but
    renaming the mapped handler method (the same event still routes to the same
    consumer) does not.
    """
    phrases = _field_change_phrases(delta.get("fields", {}))
    if phrases:
        return phrases
    if _delta_is_drawn(delta, drawn_types):
        return ["changed"]
    return []


def _draws_event(events: dict[str, Any], evt_fqn: str) -> bool:
    """Whether the model draws *evt_fqn* in a snapshot's cluster events.

    The same predicate :func:`_render_slice` applies: an event is drawn unless
    it is a fact event. An event absent from the snapshot is not drawn.
    """
    return evt_fqn in events and not events[evt_fqn].get("is_fact_event")


class _ConsumerNodes(NamedTuple):
    """Every consumer node a snapshot draws, keyed by consumer FQN.

    The renderer namespaces a consumer node by cluster, so one consumer can be
    several nodes: a handler wired to events from two aggregates is drawn in
    both slices. Each entry maps a consumer FQN to ``{cluster_fqn: label}``, the
    slices that draw it and the label each draws it with, which is the node
    topology the diff compares side to side.
    """

    read_models: dict[str, dict[str, str]]
    automations: dict[str, dict[str, str]]


def _drawn_consumer_nodes(ir: dict[str, Any]) -> _ConsumerNodes:
    """Every consumer node the event model draws anywhere in *ir*.

    A projector, event handler or process manager is a node in the diagram only
    when its ``handlers`` map matches the ``__type__`` of some cluster's non-fact
    event. Reuses the same indexes and the same matcher the renderer does, over
    every cluster, so a consumer's presence here means some slice draws it.

    The cluster dimension is kept: a consumer is one node per slice that draws
    it, so a consumer rewired from one aggregate's events to another's shows up
    as a different set of slices even though its FQN is drawn on both sides.
    """
    read_models = _read_model_index(ir)
    automations = _automation_index(ir)
    projector_nodes: dict[str, dict[str, str]] = {}
    automation_nodes: dict[str, dict[str, str]] = {}
    for cluster_fqn, cluster in ir.get("clusters", {}).items():
        consumers = _slice_consumers(read_models, automations, cluster or {})
        for proj_fqn, label in consumers.read_models.items():
            projector_nodes.setdefault(proj_fqn, {})[cluster_fqn] = label
        for consumer_fqn, label in consumers.automations.items():
            automation_nodes.setdefault(consumer_fqn, {})[cluster_fqn] = label
    return _ConsumerNodes(projector_nodes, automation_nodes)


def _cluster_change_phrases(
    cluster_fqn: str,
    delta: dict[str, Any],
    left_clusters: dict[str, Any],
    right_clusters: dict[str, Any],
    drawn_types: _DrawnEventTypes,
) -> list[str]:
    """Render one changed cluster's intrinsic slice-participant changes.

    Reports only the intrinsic participants the event model draws inside the
    slice — the aggregate (state), its non-fact events (results) and its
    commands (triggers). Consumers (event handlers, read models) are handled by
    the caller, which routes their appearance and disappearance to the added
    and removed sections. Entities, value objects, repositories, database
    models, application services, command handlers, queries and query handlers
    are not slice participants, so a change confined to one of them is not a
    model change and is intentionally left out.

    The slice is named by the aggregate, read from the right snapshot (a
    changed cluster is present on both sides). Events are classified against
    both snapshots, so the fact-event predicate that decides what the diagram
    draws is applied to whichever side the event exists on.
    """
    right_cluster = right_clusters.get(cluster_fqn, {})
    agg = right_cluster.get("aggregate", {}).get("name") or short_name(cluster_fqn)
    prefix = f"slice {agg}: "
    phrases: list[str] = []

    # Aggregate (state): named fields where there are any, otherwise a bare
    # "changed" for a delta in the options, invariants or attributes the
    # aggregate node carries.
    phrases.extend(
        f"{prefix}aggregate {phrase}"
        for phrase in _element_change_phrases(delta.get("aggregate", {}), drawn_types)
    )

    # Events (results). The diagram draws an event unless it is a fact event, so
    # each side is judged by the snapshot it exists in: an added event by the
    # right, a removed event by the left. An event that crosses the predicate
    # gains or loses its node without being added or removed, so it reads as
    # added or removed with the reason in parentheses.
    left_events = left_clusters.get(cluster_fqn, {}).get("events", {})
    right_events = right_cluster.get("events", {})
    events = delta.get("events", {})
    phrases.extend(
        f"{prefix}event {short_name(evt_fqn)} added"
        for evt_fqn in sorted(events.get("added", {}))
        if _draws_event(right_events, evt_fqn)
    )
    phrases.extend(
        f"{prefix}event {short_name(evt_fqn)} removed"
        for evt_fqn in sorted(events.get("removed", {}))
        if _draws_event(left_events, evt_fqn)
    )
    for evt_fqn, evt_delta in sorted(events.get("changed", {}).items()):
        was_drawn = _draws_event(left_events, evt_fqn)
        is_drawn = _draws_event(right_events, evt_fqn)
        name = short_name(evt_fqn)
        if was_drawn and is_drawn:
            phrases.extend(
                f"{prefix}event {name} {phrase}"
                for phrase in _element_change_phrases(evt_delta, drawn_types)
            )
        elif is_drawn:
            phrases.append(f"{prefix}event {name} added (no longer a fact event)")
        elif was_drawn:
            phrases.append(f"{prefix}event {name} removed (now a fact event)")

    # Commands (triggers): changes only. An added or removed command is a
    # gained or lost slice, reported as such by the caller.
    commands_changed = delta.get("commands", {}).get("changed", {})
    phrases.extend(
        f"{prefix}command {short_name(cmd_fqn)} {phrase}"
        for cmd_fqn, cmd_delta in sorted(commands_changed.items())
        for phrase in _element_change_phrases(cmd_delta, drawn_types)
    )

    return phrases


def _automation_deltas(diff_result: dict[str, Any]) -> dict[str, Any]:
    """Every changed automation's delta, keyed by FQN.

    Automations are the event-model consumers driven by events: event handlers
    (defined inside a cluster) and process managers (under ``flows``). Only the
    changed ones need a delta. An automation that appeared, disappeared or
    moved is read off the two snapshots' nodes instead (see
    :func:`_consumer_transitions`). That is what covers the handlers of a
    cluster added or removed whole, since the diff collapses such a cluster to a
    one-line summary, and the handler rewired to another aggregate's events,
    which the diff reports as ``event_handlers.removed`` under its old cluster
    plus ``event_handlers.added`` under its new one rather than as a change.
    """
    deltas: dict[str, Any] = {}
    for delta in diff_result.get("clusters", {}).get("changed", {}).values():
        deltas.update(delta.get("event_handlers", {}).get("changed", {}))
    process_managers = diff_result.get("flows", {}).get("process_managers", {})
    deltas.update(process_managers.get("changed", {}))
    return deltas


def _projector_deltas(diff_result: dict[str, Any]) -> dict[str, Any]:
    """Every changed projector's delta, keyed by FQN, across all projections.

    A projector retargeted from one existing projection to another is not here:
    the diff reports it as removed from the old group and added to the new one.
    Its node label carries the projection it feeds, so
    :func:`_consumer_transitions` catches the retarget as a changed node.
    """
    deltas: dict[str, Any] = {}
    for delta in diff_result.get("projections", {}).get("changed", {}).values():
        deltas.update(delta.get("projectors", {}).get("changed", {}))
    return deltas


class _ProjectorHome(NamedTuple):
    """Where a projector lives: its projection group and that group's name."""

    group_fqn: str
    read_model: str


def _projector_homes(ir: dict[str, Any]) -> dict[str, _ProjectorHome]:
    """Map every projector FQN in *ir* to the read model it feeds.

    The diff reports a projector under its read model's name, and a projector
    that is only on one side can only be named from that side's snapshot.
    """
    homes: dict[str, _ProjectorHome] = {}
    for group_fqn, group in ir.get("projections", {}).items():
        name = group.get("projection", {}).get("name") or short_name(group_fqn)
        for projector_fqn in group.get("projectors", {}):
            homes[projector_fqn] = _ProjectorHome(group_fqn, name)
    return homes


def _projector_lines(
    fqns: list[str],
    homes: dict[str, _ProjectorHome],
    whole_groups: dict[str, Any],
    suffix: str = "",
) -> list[str]:
    """Render projector FQNs as ``read model <name>: projector <name>`` lines.

    A projector whose whole projection group is in *whole_groups* (the diff's
    added or removed projections) is left out: the ``read model <name>`` line
    for the group already says the read model came or went.
    """
    lines: list[str] = []
    for fqn in fqns:
        home = homes.get(fqn)
        if home is not None and home.group_fqn in whole_groups:
            continue
        name = home.read_model if home else short_name(fqn)
        lines.append(f"read model {name}: projector {short_name(fqn)}{suffix}")
    return lines


def _consumer_transitions(
    left_nodes: dict[str, dict[str, str]],
    right_nodes: dict[str, dict[str, str]],
    deltas: dict[str, Any],
    drawn_types: _DrawnEventTypes,
) -> tuple[list[str], list[str], list[str]]:
    """Split consumer FQNs into the ones the diagram gained, lost and redrew.

    Whether a consumer is drawn is a property of the side it lives on: it needs
    a routing key that matches a non-fact event of some cluster in that
    snapshot. So appearance and disappearance are read off the two snapshots'
    nodes rather than off the diff. That catches the consumer that came or went
    because the events moved under it (its event was added, removed, or turned
    into a fact event) while the consumer element itself never changed. It also
    puts a consumer whose own delta made it drawn, such as an empty handler map
    that gained a live route, under added rather than changed.

    A consumer drawn on both sides stayed, so it is changed when the diagram
    redraws it in any way: when the slices that draw it differ (a handler
    rewired to another aggregate's events, a consumer that lost one of its two
    slices), when a node label differs (a process manager whose lifecycle
    flipped, a projector retargeted to another projection), or when its own
    delta touches something the renderer reads. A consumer drawn on neither
    side is no node in any slice, so it is left out entirely.

    Returns:
        ``(added, removed, changed)``, each a list of FQNs sorted by FQN.
    """
    added = sorted(right_nodes.keys() - left_nodes.keys())
    removed = sorted(left_nodes.keys() - right_nodes.keys())
    changed = sorted(
        fqn
        for fqn in left_nodes.keys() & right_nodes.keys()
        if left_nodes[fqn] != right_nodes[fqn]
        or _delta_is_drawn(deltas.get(fqn, {}), drawn_types)
    )
    return added, removed, changed


def generate_event_model_diff(
    diff_result: dict[str, Any],
    left_ir: dict[str, Any],
    right_ir: dict[str, Any],
) -> str:
    """Render an IR diff in EventModeling slice vocabulary.

    Takes the :func:`protean.ir.diff.diff_ir` result and both IR snapshots, and
    rewrites the diff as slice statements: an added command is a new slice, a
    removed projection is a removed read model, a projection that gained a field
    is a changed slice. The diff says what changed inside an element, and the
    snapshots supply the slice topology the diff collapses away (a whole new
    cluster is one diff entry, so its commands are enumerated from the
    snapshot).

    Only participants the event model draws are reported: commands, the
    aggregate, non-fact events, projections (read models) and automations
    (event handlers and process managers). Both snapshots are needed because
    what the model draws is a property of the side an element lives on. A
    removed event is a fact event or not according to the left snapshot. A
    consumer (a projector, an event handler, a process manager) is drawn on
    each side by that side's events, so the nodes the two snapshots draw are
    compared to decide whether its node appeared, disappeared or was redrawn.
    That is the one place a comparison is made outside the diff, and it is what
    catches a consumer that came, went or moved because the events around it
    moved while the consumer itself stayed put.

    A consumer that appears or disappears is routed to the added or removed
    section, like a new or gone slice; a change confined to a slice's intrinsic
    body (aggregate, events, command fields) is routed to the changed section
    under the slice's name. A change confined to anything else (entities,
    repositories, contracts, diagnostics, domain metadata) is not a model
    change; it does not fabricate a slice. When nothing the model draws moved,
    returns the single line ``No model changes.``.

    Args:
        diff_result: The dict returned by :func:`protean.ir.diff.diff_ir`.
        left_ir: The left-hand (baseline) IR snapshot the diff was computed
            from.
        right_ir: The right-hand (current) IR snapshot the diff was computed
            against.

    Returns:
        The rendered diff as plain text, or ``No model changes.`` when nothing
        the model draws changed.
    """
    clusters = diff_result.get("clusters", {})
    projections = diff_result.get("projections", {})

    left_clusters = left_ir.get("clusters", {})
    right_clusters = right_ir.get("clusters", {})
    right_projections = right_ir.get("projections", {})

    # Consumers (projectors, event handlers, process managers) are drawn only
    # where they match a non-fact event, so each side is judged against its own
    # snapshot: a consumer the right draws and the left does not has appeared,
    # whether it was the consumer or the events around it that moved. The nodes
    # carry the slices that draw them and the label each is drawn with, so a
    # consumer that moved between slices or was relabelled reads as changed.
    left_drawn = _drawn_consumer_nodes(left_ir)
    right_drawn = _drawn_consumer_nodes(right_ir)
    drawn_types = _DrawnEventTypes(
        _drawn_event_types(left_ir), _drawn_event_types(right_ir)
    )
    left_homes = _projector_homes(left_ir)
    right_homes = _projector_homes(right_ir)
    auto_added, auto_removed, auto_changed = _consumer_transitions(
        left_drawn.automations,
        right_drawn.automations,
        _automation_deltas(diff_result),
        drawn_types,
    )
    proj_added, proj_removed, proj_changed = _consumer_transitions(
        left_drawn.read_models,
        right_drawn.read_models,
        _projector_deltas(diff_result),
        drawn_types,
    )

    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []

    # --- Added slices and read models ----------------------------------
    # A whole new cluster collapses to one diff entry, so enumerate its
    # commands from the right snapshot: one added slice per command.
    for cluster_fqn in sorted(clusters.get("added", {})):
        cmd_fqns = sorted(right_clusters.get(cluster_fqn, {}).get("commands", {}))
        agg = short_name(cluster_fqn)
        if cmd_fqns:
            added.extend(
                f"slice {short_name(cmd_fqn)} (new cluster {agg})"
                for cmd_fqn in cmd_fqns
            )
        else:
            # A command-less new cluster has no trigger to name; name the
            # aggregate so the new cluster is never reported silently.
            added.append(f"slice {agg} (new cluster)")

    # New commands added to an existing cluster.
    for _cluster_fqn, delta in sorted(clusters.get("changed", {}).items()):
        added.extend(
            f"slice {short_name(cmd_fqn)}"
            for cmd_fqn in sorted(delta.get("commands", {}).get("added", {}))
        )

    # A new projection is a new read model.
    added.extend(
        f"read model {_summary_name(info, proj_fqn)}"
        for proj_fqn, info in sorted(projections.get("added", {}).items())
    )

    # A consumer the right snapshot draws and the left does not is a node the
    # diagram gained, so it belongs in the added section rather than as a
    # self-contradictory "~ ... added" changed line. A projector is the read
    # model's node in the slice, so it is reported here on the same terms as an
    # automation.
    added.extend(f"automation {short_name(fqn)}" for fqn in auto_added)
    added.extend(
        _projector_lines(proj_added, right_homes, projections.get("added", {}))
    )

    # --- Removed slices and read models --------------------------------
    # A whole removed cluster collapses to one diff entry, so enumerate its
    # commands from the left snapshot: one removed slice per command, mirroring
    # the added path. A command-less removed cluster is named by its aggregate.
    for cluster_fqn, info in sorted(clusters.get("removed", {}).items()):
        cmd_fqns = sorted(left_clusters.get(cluster_fqn, {}).get("commands", {}))
        agg = _summary_name(info, cluster_fqn)
        if cmd_fqns:
            removed.extend(
                f"slice {short_name(cmd_fqn)} (removed cluster {agg})"
                for cmd_fqn in cmd_fqns
            )
        else:
            removed.append(f"slice {agg} (removed cluster)")
    for _cluster_fqn, delta in sorted(clusters.get("changed", {}).items()):
        removed.extend(
            f"slice {short_name(cmd_fqn)}"
            for cmd_fqn in sorted(delta.get("commands", {}).get("removed", {}))
        )
    removed.extend(
        f"read model {_summary_name(info, proj_fqn)}"
        for proj_fqn, info in sorted(projections.get("removed", {}).items())
    )
    removed.extend(f"automation {short_name(fqn)}" for fqn in auto_removed)
    removed.extend(
        _projector_lines(proj_removed, left_homes, projections.get("removed", {}))
    )

    # --- Changed slices ------------------------------------------------
    for cluster_fqn, delta in sorted(clusters.get("changed", {}).items()):
        changed.extend(
            _cluster_change_phrases(
                cluster_fqn, delta, left_clusters, right_clusters, drawn_types
            )
        )

    # A read model changes when the projection element changes: its fields, or
    # anything else it carries. Queries and query handlers are not drawn, so
    # their deltas are left out.
    for proj_fqn, delta in sorted(projections.get("changed", {}).items()):
        name = right_projections.get(proj_fqn, {}).get("projection", {}).get(
            "name"
        ) or short_name(proj_fqn)
        changed.extend(
            f"read model {name}: {phrase}"
            for phrase in _element_change_phrases(
                delta.get("projection", {}), drawn_types
            )
        )

    # A consumer drawn on both sides is a node that stayed and was redrawn: a
    # projector rewired to a different event, an automation whose routing moved.
    # A projector carries `method_edges` too, and a delta confined to that
    # derivation moves no node, so it is not a read-model change.
    changed.extend(_projector_lines(proj_changed, right_homes, {}, " changed"))
    changed.extend(f"automation {short_name(fqn)}" for fqn in auto_changed)

    if not (added or removed or changed):
        return "No model changes."

    lines: list[str] = ["Model changes:"]
    for header, sign, entries in (
        ("Added", "+", added),
        ("Removed", "-", removed),
        ("Changed", "~", changed),
    ):
        if entries:
            lines.append("")
            lines.append(f"{header}:")
            lines.extend(f"  {sign} {entry}" for entry in entries)
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

    read_models = _read_model_index(ir)
    automations = _automation_index(ir)

    lines: list[str] = ["flowchart LR"]
    all_edges: list[str] = []
    for cluster_fqn, cluster in sorted(clusters.items()):
        subgraph_lines, edge_lines = _render_slice(
            read_models, automations, cluster_fqn, cluster
        )
        lines.extend(subgraph_lines)
        all_edges.extend(edge_lines)

    lines.extend(all_edges)
    return "\n".join(lines)
