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

#: Top-level IR keys excluded from content comparison:
#:
#: - ``$schema`` / ``ir_version`` — format and framework-version markers
#: - ``generated_at`` — the materialization timestamp
#: - ``checksum`` — the content digest itself
#: - ``elements`` — a derived index over the content sections
VOLATILE_IR_KEYS = frozenset(
    {"$schema", "ir_version", "generated_at", "checksum", "elements"}
)
