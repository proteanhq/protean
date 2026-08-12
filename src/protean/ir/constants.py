"""Shared IR constants.

Single source of truth for the top-level IR keys that are **volatile or
derived** and therefore excluded from content comparison. Both the content
checksum (:meth:`protean.ir.builder.IRBuilder._compute_checksum`) and the diff
(:func:`protean.ir.diff.diff_ir`) must treat exactly these keys as non-content,
otherwise ``protean ir check`` (staleness) and ``protean ir diff`` can disagree
on whether a domain changed. Centralising the set here
keeps the two in lockstep by construction rather than by comment.
"""

from __future__ import annotations

import json
from typing import Any

#: Libraries whose use marks a call as reaching outside the process. Shared by
#: the ``IO_INSIDE_UNIT_OF_WORK`` upgrade check and the
#: ``HANDLER_PERSISTS_AND_CALLS_OUT`` diagnostic so the two cannot drift: adding
#: a client here teaches both at once.
#:
#: Deliberately import-driven. Matching bare verb names would flag
#: ``repository_for(Order).get(id)``, the most common call there is inside a
#: Unit of Work, and a check that fires on correct code is one people learn to
#: ignore.
EXTERNAL_IO_MODULES = frozenset(
    {"httpx", "requests", "urllib", "urllib3", "aiohttp", "smtplib"}
)

#: Verbs that actually reach the network, only ever matched against a callee
#: already rooted in :data:`EXTERNAL_IO_MODULES`. Without this gate the module
#: alone would flag `urllib.parse.urlencode` (pure string work) and
#: `requests.Session` (a constructor).
EXTERNAL_IO_VERBS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request", "send"}
)

#: Names distinctive enough to count wherever the callee chain resolves to
#: them, root regardless. `publish` is the broker API; the rest are unambiguous
#: by construction. Like every entry here, a name only counts once the whole
#: callee resolves to a clean dotted path: a receiver held on a local or reached
#: through a subscript (`brokers["default"].publish`) does not resolve, so this
#: set catches the module-rooted spellings (`urllib.request.urlopen`), not the
#: receiver-held ones.
UNAMBIGUOUS_IO_NAMES = frozenset(
    {"publish", "send_email", "sendmail", "send_message", "urlopen"}
)


def is_external_io_call(callee_fqn: str | None) -> bool:
    """Does *callee_fqn* name a call that reaches outside the process?

    Two ways to count, and an unresolvable callee is never guessed at. A name in
    :data:`UNAMBIGUOUS_IO_NAMES` counts wherever the chain resolves, root
    regardless (`some.pkg.publish`). Otherwise the callee has to be both rooted
    in a known I/O library and named like a request (`httpx.post`), so the verb
    gate keeps `urllib.parse.urlencode` and `requests.Session` out.
    """
    if not callee_fqn:
        return False
    name = callee_fqn.rpartition(".")[2]
    if name in UNAMBIGUOUS_IO_NAMES:
        return True
    return callee_fqn.partition(".")[0] in EXTERNAL_IO_MODULES and name in (
        EXTERNAL_IO_VERBS
    )


#: The framework accessor that hands back a repository. Matched on the trailing
#: name rather than a full path, because `current_domain` is imported from two
#: places (`protean` and `protean.utils.globals`) that resolve to different
#: FQNs. The name is distinctive enough that a trailing match cannot collide.
PERSISTENCE_ACCESSORS = frozenset({"repository_for"})


def is_persistence_call(callee_fqn: str | None) -> bool:
    """Does *callee_fqn* name a call that reaches a repository?"""
    if not callee_fqn:
        return False
    return callee_fqn.rpartition(".")[2] in PERSISTENCE_ACCESSORS


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
