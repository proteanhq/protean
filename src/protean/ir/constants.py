"""Shared IR constants.

Single source of truth for the top-level IR keys that are **volatile or
derived** and therefore excluded from content comparison. Both the content
checksum (:meth:`protean.ir.builder.IRBuilder._compute_checksum`) and the diff
(:func:`protean.ir.diff.diff_ir`) must treat exactly these keys as non-content,
otherwise ``protean ir check`` (staleness) and ``protean ir diff`` can disagree
on whether a domain changed — the bug fixed in #1012. Centralising the set here
keeps the two in lockstep by construction rather than by comment.
"""

from __future__ import annotations

import json
from typing import Any

#: Top-level IR keys excluded from content comparison:
#:
#: - ``$schema`` / ``ir_version`` — format and framework-version markers
#: - ``generated_at`` — the materialization timestamp
#: - ``checksum`` — the content digest itself
#: - ``elements`` — a derived index over the content sections
VOLATILE_IR_KEYS = frozenset(
    {"$schema", "ir_version", "generated_at", "checksum", "elements"}
)

#: Top-level IR keys stripped from the **canonical baseline** output
#: (``protean ir show --canonical`` and the ``--fix`` staleness hook).
#:
#: Distinct from (and a strict subset of) :data:`VOLATILE_IR_KEYS` above:
#: that set governs *content comparison* (what ``ir diff``/checksum ignore),
#: whereas this one governs *baseline serialization* (what gets stripped from a
#: persisted snapshot). A baseline keeps ``checksum``/``elements``/version
#: markers for readability; only ``generated_at`` is non-deterministic noise.
#:
#: Only the non-deterministic materialization timestamp ``generated_at`` is
#: removed. ``$schema``/``ir_version`` (readable version markers) and
#: ``checksum``/``elements`` (content-derived, stable given the same content)
#: are retained — all four are already ignored by ``ir diff`` and ``ir check``.
#: The result is a baseline that changes only when the domain *contract* does,
#: keeping committed ``.protean/ir.json`` diffs free of timestamp churn.
CANONICAL_EXCLUDED_KEYS = frozenset({"generated_at"})


def canonical_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *ir* with :data:`CANONICAL_EXCLUDED_KEYS` removed.

    Use for materialized baselines committed to version control, where the
    volatile ``generated_at`` timestamp is pure noise: it churns on every
    regeneration even when the contract is unchanged. The returned IR compares
    identically under ``ir diff`` and ``ir check`` (both ignore the stripped
    keys), so a canonical baseline only ever changes when the domain does.
    """
    return {k: v for k, v in ir.items() if k not in CANONICAL_EXCLUDED_KEYS}


def canonical_ir_json(ir: dict[str, Any]) -> str:
    """Serialize *ir* to the canonical baseline JSON string (no trailing newline).

    The single source of truth for how a committed ``.protean/ir.json`` baseline
    is rendered: :func:`canonical_ir` (drop volatile keys) plus deterministic,
    key-sorted, 2-space-indented JSON. Every baseline writer routes through this
    — ``protean ir show --canonical``, the ``--fix`` staleness hook, and
    ``protean schema generate`` (``write_ir``) — so they all emit byte-identical
    output; otherwise timestamp or key-ordering differences would reintroduce
    the very churn this feature removes.
    """
    return json.dumps(canonical_ir(ir), indent=2, sort_keys=True)
