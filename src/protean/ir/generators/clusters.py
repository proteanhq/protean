"""Aggregate cluster diagram generator.

Produces Mermaid ``classDiagram`` output from an IR dict, rendering each
aggregate cluster as a class with its fields, related entities, value
objects, and cross-aggregate references.

Usage::

    from protean.ir.generators.clusters import generate_cluster_diagram

    diagram = generate_cluster_diagram(ir)             # all clusters
    diagram = generate_cluster_diagram(ir, cluster_fqn="app.Order")  # one
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import (
    field_summary,
    mermaid_escape,
    sanitize_mermaid_id,
    short_name,
)


def _render_class(
    name: str,
    element: dict[str, Any],
    *,
    stereotype: str = "",
) -> list[str]:
    """Render a single element as a Mermaid class block with fields."""
    sid = sanitize_mermaid_id(name)
    lines: list[str] = []
    lines.append(f"    class {sid} {{")

    if stereotype:
        lines.append(f"        <<{stereotype}>>")

    fields = element.get("fields", {})
    for fname, fspec in sorted(fields.items()):
        summary = field_summary(fspec)
        lines.append(f"        +{mermaid_escape(fname)} {mermaid_escape(summary)}")

    lines.append("    }")
    return lines


def _aggregate_stereotype(aggregate: dict[str, Any]) -> str:
    """Build the stereotype string for an aggregate."""
    options = aggregate.get("options", {})
    parts: list[str] = ["Aggregate"]
    if options.get("is_event_sourced"):
        parts.append("EventSourced")
    if options.get("fact_events"):
        parts.append("FactEvents")
    return ", ".join(parts)


def _render_invariant_notes(sid: str, invariants: dict[str, list[str]]) -> list[str]:
    """Render invariant names as Mermaid notes attached to a class."""
    names = invariants.get("pre", []) + invariants.get("post", [])
    if not names:
        return []
    label = ", ".join(names)
    escaped_label = mermaid_escape(label)
    return [f"    note for {sid} {escaped_label}"]


def _render_cluster(
    cluster_fqn: str,
    cluster: dict[str, Any],
) -> list[str]:
    """Render a single aggregate cluster as Mermaid classDiagram lines."""
    lines: list[str] = []
    agg = cluster["aggregate"]
    agg_sid = sanitize_mermaid_id(cluster_fqn)

    # Aggregate class
    stereotype = _aggregate_stereotype(agg)
    lines.extend(_render_class(cluster_fqn, agg, stereotype=stereotype))
    lines.extend(_render_invariant_notes(agg_sid, agg.get("invariants", {})))

    # Entities
    for entity_fqn, entity in sorted(cluster.get("entities", {}).items()):
        entity_sid = sanitize_mermaid_id(entity_fqn)
        entity_short = short_name(entity_fqn)
        lines.extend(_render_class(entity_fqn, entity, stereotype="Entity"))
        lines.extend(_render_invariant_notes(entity_sid, entity.get("invariants", {})))

        # has_many from aggregate to entity
        for _fname, fspec in sorted(agg.get("fields", {}).items()):
            if fspec.get("kind") == "has_many" and fspec.get("target") == entity_fqn:
                lines.append(
                    f'    {agg_sid} "1" o-- "*" {entity_sid}'
                    f" : {mermaid_escape(entity_short)}"
                )

    # Value Objects
    for vo_fqn, vo in sorted(cluster.get("value_objects", {}).items()):
        vo_sid = sanitize_mermaid_id(vo_fqn)
        vo_short = short_name(vo_fqn)
        lines.extend(_render_class(vo_fqn, vo, stereotype="ValueObject"))
        lines.extend(_render_invariant_notes(vo_sid, vo.get("invariants", {})))

        # composition from aggregate to VO
        for _fname, fspec in sorted(agg.get("fields", {}).items()):
            if fspec.get("kind") in ("value_object", "value_object_list"):
                if fspec.get("target") == vo_fqn:
                    lines.append(
                        f"    {agg_sid} *-- {vo_sid} : {mermaid_escape(vo_short)}"
                    )

    return lines


def _collect_cross_references(
    ir: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Find cross-aggregate reference fields.

    Returns a list of (source_class_fqn, target_aggregate_fqn, field_name)
    tuples for every ``reference`` field that points to a different aggregate.
    """
    refs: list[tuple[str, str, str]] = []
    clusters = ir.get("clusters", {})

    for cluster_fqn, cluster in clusters.items():
        # Check entity reference fields that point to other aggregates
        for entity_fqn, entity in cluster.get("entities", {}).items():
            for fname, fspec in entity.get("fields", {}).items():
                if fspec.get("kind") == "reference":
                    target = fspec.get("target", "")
                    # Only cross-aggregate references (not self-referencing)
                    if target and target != cluster_fqn:
                        refs.append((entity_fqn, target, fname))

        # Check aggregate fields for reference kind
        agg = cluster.get("aggregate", {})
        for fname, fspec in agg.get("fields", {}).items():
            if fspec.get("kind") == "reference":
                target = fspec.get("target", "")
                if target and target != cluster_fqn:
                    refs.append((cluster_fqn, target, fname))

    return sorted(refs)


def generate_cluster_diagram(
    ir: dict[str, Any],
    *,
    cluster_fqn: str = "",
) -> str:
    """Generate a Mermaid ``classDiagram`` from IR clusters.

    Args:
        ir: The full IR dict.
        cluster_fqn: If given, generate a diagram for a single cluster.
            Otherwise all clusters are rendered.

    Returns:
        A string containing the Mermaid ``classDiagram`` source.
    """
    clusters = ir.get("clusters", {})
    if not clusters:
        return "classDiagram"

    lines: list[str] = ["classDiagram"]

    if cluster_fqn:
        cluster = clusters.get(cluster_fqn)
        if cluster is None:
            return "classDiagram"
        lines.extend(_render_cluster(cluster_fqn, cluster))
    else:
        for cfqn, cluster in sorted(clusters.items()):
            lines.extend(_render_cluster(cfqn, cluster))

        # Cross-aggregate references
        for source_fqn, target_fqn, fname in _collect_cross_references(ir):
            src_sid = sanitize_mermaid_id(source_fqn)
            tgt_sid = sanitize_mermaid_id(target_fqn)
            lines.append(f"    {src_sid} ..> {tgt_sid} : {mermaid_escape(fname)}")

    return "\n".join(lines)
