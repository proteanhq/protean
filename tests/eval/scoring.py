"""Score a produced project's IR against the gold's, per-element partial credit.

The base rubric the comparison eval reports is a fraction: of the structural
elements the gold carries, how many the produced project recovers, every element
weighted equally (a missing field counts the same as a missing aggregate). The
scored categories are exactly the ones the epic names: aggregates, fields,
commands, events, and handlers (command handlers and event handlers).

Matching is by class name, not by fully-qualified name. The gold project (built
from ``protean add``) and a context-driven project use different package names,
so any FQN-based match would score zero everywhere. An element is recovered when
the produced IR carries one of the same category with the same class name (the
final segment of the FQN). Fields match on ``(aggregate class name, field
name)``, so renaming an aggregate drops every field under it. Matching is exact
per category; fuzzy or semantic matching is a later dimension beyond this rubric.

Class-name matching can only score a gold whose class names tell its elements
apart. A gold carrying ``sales.commands.CreateOrder`` and
``billing.commands.CreateOrder`` reduces both to one signature, which would
undercount the denominator and let a single produced command recover two gold
elements. :func:`score` raises :class:`AmbiguousGoldError` on such a gold rather
than reporting that number.

On top of that base recall, :func:`score_boundary` adds two boundary-aware
scores the flat rubric cannot see. Placement reads the per-aggregate ``clusters``
to ask whether each recovered command, event, handler, or entity sits under the
right aggregate; context asks whether each recovered aggregate sits in the right
bounded context (its package-relative module segment). The same element names
under the wrong aggregate score high on the base rubric and low on placement,
which is what tells a wrong decomposition apart. The base ``score`` and
``Correctness`` are unchanged; the boundary layer is returned alongside as
:class:`Recovery`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AmbiguousGoldError",
    "Correctness",
    "Recovery",
    "Signature",
    "element_signatures",
    "score",
    "score_boundary",
]

# A structural element reduced to what the rubric matches on. A category element
# is ``(category, class_name)``; a field is ``("field", aggregate_name,
# field_name)``. Both are plain string tuples, so a set of them compares by value
# and sorts cleanly for a readable report.
Signature = tuple[str, ...]

# IR element-type keys mapped to the rubric category name. Command handlers and
# event handlers both score as "handler", so a handler recovered under either
# kind counts, per the epic's "handlers (command handlers and event handlers)".
_SCORED_CATEGORIES = {
    "AGGREGATE": "aggregate",
    "COMMAND": "command",
    "EVENT": "event",
    "COMMAND_HANDLER": "handler",
    "EVENT_HANDLER": "handler",
}

# The per-cluster element sections whose placement under an aggregate the
# boundary score reads, mapped to the same rubric category names as above. A
# command handler and an event handler both score as "handler", so a handler in
# either section keys the same way. Aggregates and fields are left out: an
# aggregate's placement is itself, and a field already keys on its aggregate in
# the base rubric.
_CLUSTER_ELEMENT_SECTIONS = {
    "commands": "command",
    "events": "event",
    "command_handlers": "handler",
    "event_handlers": "handler",
    "entities": "entity",
}


class AmbiguousGoldError(ValueError):
    """The gold IR carries elements its class names cannot tell apart."""


@dataclass(frozen=True)
class Correctness:
    """The correctness score plus the breakdown behind it.

    ``score`` is ``len(recovered) / expected`` in ``[0, 1]``, or ``0.0`` when the
    gold carries no scored element (the empty-input guard). ``recovered`` and
    ``missing`` are the gold signatures the produced project did and did not
    carry, sorted for a readable report and for the later scoring and variance
    dimensions to build on. ``expected`` is the count of gold signatures, the
    denominator.
    """

    score: float
    recovered: tuple[Signature, ...]
    missing: tuple[Signature, ...]
    expected: int


@dataclass(frozen=True)
class Recovery:
    """The boundary/aggregate recovery scores plus the breakdown behind them.

    ``placement`` is the fraction of the gold's per-cluster elements (commands,
    events, handlers, entities) the produced project both recovers by class name
    *and* attaches to the correct aggregate: ``len(placed) / placement_expected``,
    where ``placement_expected`` is the count the produced project recovers. The
    denominator is that recovered count, so placement scores only the elements the
    project got back, on whether each landed under the right aggregate. This is the
    discriminator a wrong decomposition fails: the same element names under the
    wrong aggregate score high on the base rubric and low here.

    ``context`` is the fraction of the gold's recovered aggregates whose bounded
    context (the package-relative first module segment) matches the gold's:
    ``len(contexts_matched) / context_expected``. It is meaningful only on a
    multi-context task; a single-context task scores 1.0 when its one aggregate is
    recovered under the same segment.

    Both scores are ``0.0`` when their denominator is zero (an empty produced or
    gold IR), the same empty-input guard the base rubric uses. ``placed``,
    ``misplaced``, ``contexts_matched``, and ``contexts_mismatched`` are sorted for
    a readable report.
    """

    placement: float
    context: float
    placed: tuple[Signature, ...]
    misplaced: tuple[Signature, ...]
    placement_expected: int
    contexts_matched: tuple[str, ...]
    contexts_mismatched: tuple[str, ...]
    context_expected: int


def _class_name(fqn: str) -> str:
    """The final ``.``-separated segment of an IR FQN, its class name."""
    return fqn.rsplit(".", 1)[-1]


def _signature_sources(ir: dict[str, Any]) -> dict[Signature, set[str]]:
    """Map each signature in *ir* to the IR elements that produced it.

    The source of a category element is its FQN; the source of a field is its
    cluster key (the aggregate's FQN) plus the field name. Two sources under one
    signature mean the IR carries two distinct elements the rubric's class-name
    matching cannot tell apart, which :func:`score` rejects in a gold.
    """
    if not isinstance(ir, dict):
        return {}
    sources: dict[Signature, set[str]] = defaultdict(set)

    elements = ir.get("elements")
    if isinstance(elements, dict):
        for ir_key, category in _SCORED_CATEGORIES.items():
            for fqn in elements.get(ir_key) or []:
                if isinstance(fqn, str):
                    sources[(category, _class_name(fqn))].add(fqn)

    clusters = ir.get("clusters")
    if isinstance(clusters, dict):
        for cluster_key, cluster in clusters.items():
            if not isinstance(cluster, dict):
                continue
            aggregate = cluster.get("aggregate")
            if not isinstance(aggregate, dict):
                continue
            fields = aggregate.get("fields")
            if not isinstance(fields, dict):
                continue
            aggregate_name = aggregate.get("name") or _class_name(
                str(aggregate.get("fqn", ""))
            )
            if not aggregate_name:
                # No name and no fqn: skip rather than key every field under the
                # empty string, where two such aggregates would collide. Real IR
                # always carries a name, so this only guards a malformed input.
                continue
            for field_name in fields:
                sources[("field", str(aggregate_name), str(field_name))].add(
                    f"{cluster_key}.{field_name}"
                )

    return dict(sources)


def element_signatures(ir: dict[str, Any]) -> set[Signature]:
    """Extract the scored elements of *ir* as a set of signatures.

    Reads the category-to-FQN lists under ``elements`` for aggregates, commands,
    events, and handlers, and the per-aggregate ``clusters`` for fields. An
    empty or malformed IR (a ``{}`` from :func:`tests.eval.ir_probe.build_ir`
    when the project has no readable domain) yields an empty set. Reads only
    class names and field names, never a volatile key such as ``checksum`` or a
    timestamp, so a signature never differs run to run.
    """
    return set(_signature_sources(ir))


def _reject_ambiguous_gold(sources: dict[Signature, set[str]]) -> None:
    """Raise when a gold signature was reached by more than one IR element.

    Only the gold is checked. A collision in the produced IR is harmless: the
    gold still asks for one element, and one of the produced elements matching
    it is a real recovery. A collision in the gold is not, because it shrinks
    the denominator every approach is scored against.
    """
    ambiguous = sorted(
        (signature, sorted(elements))
        for signature, elements in sources.items()
        if len(elements) > 1
    )
    if not ambiguous:
        return
    detail = "; ".join(
        f"{'/'.join(signature)} <- {', '.join(elements)}"
        for signature, elements in ambiguous
    )
    raise AmbiguousGoldError(
        "gold IR carries elements the rubric's class-name matching cannot tell "
        f"apart, so the denominator would undercount them: {detail}"
    )


def score(produced_ir: dict[str, Any], gold_ir: dict[str, Any]) -> Correctness:
    """Score *produced_ir* against *gold_ir* as recovered / expected.

    Every gold signature the produced IR also carries is recovered; the rest are
    missing. When the gold carries no scored element the score is ``0.0`` with an
    expected count of zero (the guard against dividing by zero); the gold always
    carries at least one aggregate, so this only guards an input the gold never
    actually produces.

    Raises :class:`AmbiguousGoldError` when two of the gold's elements share a
    category and a class name. The score would then be measured against a
    denominator short of the elements the gold actually carries, and a single
    produced element would appear to recover both.
    """
    gold_sources = _signature_sources(gold_ir)
    _reject_ambiguous_gold(gold_sources)
    gold = set(gold_sources)
    produced = element_signatures(produced_ir)
    if not gold:
        return Correctness(score=0.0, recovered=(), missing=(), expected=0)
    recovered = gold & produced
    missing = gold - produced
    return Correctness(
        score=len(recovered) / len(gold),
        recovered=tuple(sorted(recovered)),
        missing=tuple(sorted(missing)),
        expected=len(gold),
    )


def _owned_clusters(ir: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Return each cluster in *ir* paired with its aggregate's class name.

    A cluster whose ``aggregate`` has neither a ``name`` nor an ``fqn`` is
    skipped, so its elements never key under the empty string (where two such
    clusters would collide). Real IR always carries a name, so this only guards a
    malformed input, mirroring the base rubric's field guard.
    """
    clusters = ir.get("clusters") if isinstance(ir, dict) else None
    if not isinstance(clusters, dict):
        return []
    owned: list[tuple[dict[str, Any], str]] = []
    for cluster in clusters.values():
        if not isinstance(cluster, dict):
            continue
        aggregate = cluster.get("aggregate")
        if not isinstance(aggregate, dict):
            continue
        owner = aggregate.get("name") or _class_name(str(aggregate.get("fqn", "")))
        if not owner:
            continue
        owned.append((cluster, str(owner)))
    return owned


def _member_name(member: Any, fqn: str) -> str:
    """The class name of a cluster member, from its ``name`` or its FQN key."""
    if isinstance(member, dict):
        name = member.get("name")
        if name:
            return str(name)
    return _class_name(str(fqn))


def _placement_sources(ir: dict[str, Any]) -> dict[Signature, set[str]]:
    """Map each per-cluster element signature to the aggregate(s) that own it.

    A signature is ``(category, class_name)`` for a command, event, handler, or
    entity; its owners are the class names of the aggregates whose clusters carry
    an element of that signature. In a well-formed gold each signature has exactly
    one owner. Two owners for one signature means the same element name sits under
    two aggregates, which :func:`_reject_ambiguous_placement` rejects in a gold.
    """
    sources: dict[Signature, set[str]] = defaultdict(set)
    for cluster, owner in _owned_clusters(ir):
        for section, category in _CLUSTER_ELEMENT_SECTIONS.items():
            members = cluster.get(section)
            if not isinstance(members, dict):
                continue
            for fqn, member in members.items():
                name = _member_name(member, str(fqn))
                if name:
                    sources[(category, name)].add(owner)
    return dict(sources)


def _reject_ambiguous_placement(sources: dict[Signature, set[str]]) -> None:
    """Raise when a gold element name is placed under more than one aggregate.

    The base ``AmbiguousGoldError`` guard already catches a class name repeated
    across the flat ``elements`` map; this covers the placement-only case of an
    entity name (which the base rubric does not score) repeated across clusters,
    so the gold's correct placement stays a single, defined aggregate.
    """
    ambiguous = sorted(
        ("/".join(signature), sorted(owners))
        for signature, owners in sources.items()
        if len(owners) > 1
    )
    if not ambiguous:
        return
    detail = "; ".join(
        f"{signature} <- aggregates {', '.join(owners)}"
        for signature, owners in ambiguous
    )
    raise AmbiguousGoldError(
        "gold IR places an element of the same class name under more than one "
        f"aggregate, so its correct placement is undefined: {detail}"
    )


def _context_segment(module: str, package: str) -> str:
    """The bounded-context segment of *module*, its first package-relative part.

    The scaffold puts each aggregate under ``<package>.<context>.<kind>`` (an
    ``Order`` aggregate lands at ``shop.order.aggregate``), so the context is the
    first module segment after the package. Stripping the package first is what
    lets a gold under package ``sales`` and a produced project under ``app`` still
    match on the ``order`` segment. When *module* does not start with *package*
    (a malformed input) its own first segment is used.
    """
    segments = [segment for segment in module.split(".") if segment]
    if package and segments and segments[0] == package:
        segments = segments[1:]
    return segments[0] if segments else ""


def _package_prefix(modules: list[str]) -> str:
    """The import package every aggregate module in *modules* sits under.

    The package is read from the modules themselves, not from the IR's domain
    metadata: ``domain.name`` is the logical name the ``Domain(name=...)`` call
    carries, which a project is free to set to something other than its import
    package. A project packaged as ``ecommerce`` but named ``Ordering`` would
    strip nothing, and every aggregate would key on ``ecommerce`` (one context
    for the whole project) instead of on its own context segment.

    Under ADR-0030 a project's domain code lives under a single import package,
    so the package is the first segment all the aggregate modules share. Returns
    ``""`` when they share no first segment, or when any of them is a single
    segment (an aggregate at the package root, which has no context segment to
    strip down to): nothing is stripped and each module's own first segment is
    the context.
    """
    firsts = set()
    for module in modules:
        segments = [segment for segment in module.split(".") if segment]
        if len(segments) < 2:
            return ""
        firsts.add(segments[0])
    if len(firsts) != 1:
        return ""
    return firsts.pop()


def _context_map(ir: dict[str, Any]) -> dict[str, str]:
    """Map each aggregate's class name to its bounded-context segment."""
    owned = [
        (str(cluster["aggregate"].get("module", "")), owner)
        for cluster, owner in _owned_clusters(ir)
    ]
    package = _package_prefix([module for module, _ in owned])
    return {owner: _context_segment(module, package) for module, owner in owned}


def score_boundary(produced_ir: dict[str, Any], gold_ir: dict[str, Any]) -> Recovery:
    """Score *produced_ir*'s aggregate boundaries and bounded contexts vs *gold_ir*.

    Placement is, of the gold's per-cluster elements the produced project recovers
    by class name, the fraction it attaches to the correct aggregate. Context is, of
    the gold's aggregates the produced project recovers, the fraction that sit in
    the matching bounded context. Both are ``0.0`` when nothing is recovered (an
    empty produced or gold IR), the same guard the base rubric uses, so neither
    divides by zero.

    Raises :class:`AmbiguousGoldError` when the gold cannot be scored by class
    name: two elements sharing a category and class name (the base guard) or one
    element name placed under two aggregates (the placement guard). Either would
    make the gold's correct placement undefined.
    """
    _reject_ambiguous_gold(_signature_sources(gold_ir))
    gold_placement = _placement_sources(gold_ir)
    _reject_ambiguous_placement(gold_placement)
    produced_placement = _placement_sources(produced_ir)

    placed: list[Signature] = []
    misplaced: list[Signature] = []
    for signature, owners in gold_placement.items():
        produced_owners = produced_placement.get(signature)
        if not produced_owners:
            continue  # not recovered at all, so not a placement to judge
        gold_owner = next(iter(owners))
        if gold_owner in produced_owners:
            placed.append(signature)
        else:
            misplaced.append(signature)
    placement_expected = len(placed) + len(misplaced)
    placement = len(placed) / placement_expected if placement_expected else 0.0

    gold_context = _context_map(gold_ir)
    produced_context = _context_map(produced_ir)
    matched: list[str] = []
    mismatched: list[str] = []
    for aggregate, segment in gold_context.items():
        produced_segment = produced_context.get(aggregate)
        if produced_segment is None:
            continue  # aggregate not recovered, so no context to judge
        if produced_segment == segment:
            matched.append(aggregate)
        else:
            mismatched.append(aggregate)
    context_expected = len(matched) + len(mismatched)
    context = len(matched) / context_expected if context_expected else 0.0

    return Recovery(
        placement=placement,
        context=context,
        placed=tuple(sorted(placed)),
        misplaced=tuple(sorted(misplaced)),
        placement_expected=placement_expected,
        contexts_matched=tuple(sorted(matched)),
        contexts_mismatched=tuple(sorted(mismatched)),
        context_expected=context_expected,
    )
