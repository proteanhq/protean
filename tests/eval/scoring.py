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
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AmbiguousGoldError",
    "Correctness",
    "Signature",
    "element_signatures",
    "score",
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
