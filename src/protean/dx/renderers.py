"""Renderers that turn the DX pack into the files ``protean dx`` writes.

Each renderer builds a :class:`~protean.dx.managed_files.ManagedBlock` for one
target file, so the managed-file writer can create it and later refresh it
without touching the user's own edits. This cut ships two targets:

- ``AGENTS.md`` — the canonical, cross-agent instruction file. Its body composes
  two layers: the positive guidance from the packaged AGENTS.md source
  (:func:`~protean.dx.pack.load_agents_source`) and the negative hard-rules
  section derived from the diagnostics registry
  (:func:`~protean.ir.generators.agents.generate_agents_md`). Both are stamped to
  the installed framework version, so an agent always reads guidance that matches
  the installed code.
- ``CLAUDE.md`` — a one-line bridge (``@AGENTS.md``) that points Claude Code at
  the canonical file.

Both targets are Markdown, so the managed block is wrapped in HTML comment
markers. The per-editor renderers (Cursor, Copilot, opencode) and the
``.mcp.json`` renderer are separate sub-issues on the developer-experience epic
and are not built here.
"""

from __future__ import annotations

from protean.dx.managed_files import ManagedBlock, ManagedFile
from protean.dx.pack import load_agents_source
from protean.ir.generators.agents import generate_agents_md

__all__ = [
    "AGENTS_TARGET",
    "BLOCK_ID",
    "CLAUDE_BRIDGE_BODY",
    "CLAUDE_BRIDGE_TARGET",
    "agents_managed_file",
    "claude_bridge_managed_file",
    "managed_files",
    "render_agents_body",
]

# The files this cut writes and the block id that frames the framework-owned
# region in each. A single block id per file keeps other tools' blocks (with
# different ids) untouched in the same file (see ADR-0037).
AGENTS_TARGET = "AGENTS.md"
CLAUDE_BRIDGE_TARGET = "CLAUDE.md"
BLOCK_ID = "protean"

# The Markdown comment syntax the managed block uses to frame its region.
_COMMENT_PREFIX = "<!-- "
_COMMENT_SUFFIX = " -->"

# The whole body of the CLAUDE.md bridge: one line pointing Claude Code at the
# canonical AGENTS.md. It carries no version, so it never churns on an upgrade.
CLAUDE_BRIDGE_BODY = "@AGENTS.md"


def _strip_leading_h1(text: str) -> str:
    """Return *text* with a leading ``# `` H1 line (and one blank after) removed.

    The composed AGENTS.md carries a single, version-stamped H1 that this module
    emits. Both source fragments (the pack source and the hard-rules section)
    bring their own H1, so drop each fragment's H1 before composing to avoid
    stacking three H1s in one file. A fragment with no leading H1 is returned
    unchanged, so this degrades safely if a fragment's shape changes.
    """
    lines = text.split("\n")
    index = 0
    while index < len(lines) and lines[index].strip() == "":
        index += 1
    if index < len(lines) and lines[index].startswith("# "):
        del lines[index]
        if index < len(lines) and lines[index].strip() == "":
            del lines[index]
    return "\n".join(lines)


def render_agents_body(version: str) -> str:
    """Compose the AGENTS.md managed-block body for *version*.

    Leads with a single version-stamped H1, then the packaged AGENTS.md source
    (positive guidance), then the diagnostics-derived hard-rules section
    (negative constraints). Each source fragment's own leading H1 is dropped and
    one version-stamped H1 leads the file, so the file has one H1 as long as each
    fragment carries at most one (the packaged source and the hard-rules section
    both do; ``test_source_fragments_each_have_at_most_one_h1`` guards it). The
    result is deterministic for a given *version*: the pack source is static
    package data and the hard-rules section is a sorted, version-stamped traversal
    of the diagnostics registry that reads no timestamp.
    """
    source = _strip_leading_h1(load_agents_source()).strip("\n")
    rules = _strip_leading_h1(generate_agents_md(version=version)).strip("\n")
    return f"# Protean agent guidance ({version})\n\n{source}\n\n{rules}"


def _markdown_block(target: str, version: str, body: str) -> ManagedBlock:
    """Build a Markdown managed block: one ``protean`` block framed by HTML
    comment markers. Centralizes the block id and comment syntax so every file
    ``dx`` writes shares them (see ADR-0037)."""
    return ManagedBlock(
        target=target,
        version=version,
        block_id=BLOCK_ID,
        body=body,
        comment_prefix=_COMMENT_PREFIX,
        comment_suffix=_COMMENT_SUFFIX,
    )


def agents_managed_file(version: str) -> ManagedBlock:
    """Return the managed block for the project's ``AGENTS.md``."""
    return _markdown_block(AGENTS_TARGET, version, render_agents_body(version))


def claude_bridge_managed_file(version: str) -> ManagedBlock:
    """Return the managed block for the project's ``CLAUDE.md`` bridge.

    The body is version-independent, but the block still carries *version* as its
    stamp so its state row advances in step with the AGENTS.md render on an
    upgrade.
    """
    return _markdown_block(CLAUDE_BRIDGE_TARGET, version, CLAUDE_BRIDGE_BODY)


def managed_files(version: str) -> tuple[ManagedFile, ...]:
    """Return every managed file ``protean dx`` writes, in a stable order.

    AGENTS.md comes first so the CLAUDE.md bridge that points at it is written
    second. Both are stamped to *version*.
    """
    return (
        agents_managed_file(version),
        claude_bridge_managed_file(version),
    )
