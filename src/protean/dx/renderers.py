"""Renderers that turn the DX pack into the files ``protean dx`` writes.

Each renderer builds a managed-file request for one target, so the managed-file
writer can create it and later refresh it without touching the user's own edits.
Six targets ship, split into the canonical set and the per-editor set.

The canonical set:

- ``AGENTS.md``: the canonical, cross-agent instruction file. Its body composes
  two layers: the positive guidance from the packaged AGENTS.md source
  (:func:`~protean.dx.pack.load_agents_source`) and the negative hard-rules
  section derived from the diagnostics registry
  (:func:`~protean.ir.generators.agents.generate_agents_md`). Both are stamped to
  the installed framework version, so an agent always reads guidance that matches
  the installed code.
- ``CLAUDE.md``: a one-line bridge (``@AGENTS.md``) that points Claude Code at
  the canonical file.
- ``.mcp.json``: the MCP server registration a client reads to launch Protean's
  MCP server. It is a managed-JSON-keys target scoped to the ``mcpServers.protean``
  key-path, so an existing ``.mcp.json`` keeps the user's other servers.

The per-editor set:

- ``.cursor/rules/protean.mdc``: Cursor's rule file. MDC: YAML frontmatter
  (``description``, ``globs: "**/*.py"``, ``alwaysApply: false``) at line 1, then
  a version stamp and the composed guidance body. Cursor reads AGENTS.md natively
  for the always-on layer, so this rule is scoped to Python files via ``globs``.
  The frontmatter must be the first bytes of the file, with no marker line above
  it, so ``dx`` owns and renders the whole file.
- ``.github/copilot-instructions.md``: Copilot's instructions. Plain Markdown
  with the guidance in an HTML-comment managed block, so the file stays co-owned
  with the user's own instructions.
- ``opencode.json``: opencode's config. A managed-JSON-keys target on the
  ``mcp.protean`` key-path with opencode's own launch shape (``type: "local"``,
  ``command`` as a list, ``enabled: true``), which differs from ``.mcp.json``'s
  shape. opencode reads AGENTS.md natively, so it gets no separate instruction
  file: this config only supplies the MCP registration.

All six go through the same managed-file writer, so ``dx check`` flags any
drifted file, per-editor ones included.
"""

from __future__ import annotations

from typing import Any

from protean.dx.managed_files import (
    ManagedBlock,
    ManagedFile,
    ManagedJsonKeys,
    ManagedWholeFile,
)
from protean.dx.pack import load_agents_source
from protean.ir.generators.agents import generate_agents_md
from protean.mcp import mcp_registration

__all__ = [
    "AGENTS_TARGET",
    "BLOCK_ID",
    "CLAUDE_BRIDGE_BODY",
    "CLAUDE_BRIDGE_TARGET",
    "COPILOT_TARGET",
    "CURSOR_TARGET",
    "MCP_SERVER_KEY",
    "MCP_SERVER_NAME",
    "MCP_TARGET",
    "OPENCODE_MCP_KEY",
    "OPENCODE_SERVER_NAME",
    "OPENCODE_TARGET",
    "agents_managed_file",
    "claude_bridge_managed_file",
    "copilot_managed_file",
    "cursor_managed_file",
    "managed_files",
    "mcp_json_managed_file",
    "opencode_managed_file",
    "opencode_registration",
    "render_agents_body",
    "render_cursor_body",
]

# The files this cut writes and the block id that frames the framework-owned
# region in each. A single block id per file keeps other tools' blocks (with
# different ids) untouched in the same file (see ADR-0037).
AGENTS_TARGET = "AGENTS.md"
CLAUDE_BRIDGE_TARGET = "CLAUDE.md"
BLOCK_ID = "protean"

# The ``.mcp.json`` target and the key-path it manages: Protean's own entry under
# ``mcpServers``, the top-level key an MCP client reads a project ``.mcp.json``
# from. Managing only ``mcpServers.protean`` keeps every other server the user
# configured (see ADR-0037's key-path JSON merge). The repo's own ``.mcp.json``
# and the snippet in the MCP reference carry the same key; the renderer tests
# pin all three together.
MCP_TARGET = ".mcp.json"
MCP_SERVER_KEY = "mcpServers"
MCP_SERVER_NAME = "protean"

# The per-editor targets. Cursor's rule file is a
# whole-file dx-owned render; Copilot's instructions carry the guidance in a
# managed block; opencode's config manages one ``mcp`` entry via the key-path
# JSON merge.
CURSOR_TARGET = ".cursor/rules/protean.mdc"
COPILOT_TARGET = ".github/copilot-instructions.md"
OPENCODE_TARGET = "opencode.json"

# opencode's config nests MCP servers under a top-level ``mcp`` object, so the
# managed key-path is ``mcp.protean``. Managing only that key keeps the user's
# other opencode keys and other mcp servers.
OPENCODE_MCP_KEY = "mcp"
OPENCODE_SERVER_NAME = "protean"

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

    The block carries *version* as its stamp so its state row advances in step
    with the AGENTS.md render on an upgrade. The body text is the same across
    versions.
    """
    return _markdown_block(CLAUDE_BRIDGE_TARGET, version, CLAUDE_BRIDGE_BODY)


def mcp_json_managed_file(version: str) -> ManagedJsonKeys:
    """Return the managed-JSON-keys request for the project's ``.mcp.json``.

    Manages only the ``mcpServers.protean`` key-path, so an existing ``.mcp.json``
    keeps every other server. The value is the launch shape
    :func:`~protean.mcp.mcp_registration` defines. The request carries *version*
    as its stamp so its state row advances in step with the other files on an
    upgrade. The registration itself is the same across versions.
    """
    return ManagedJsonKeys(
        target=MCP_TARGET,
        version=version,
        data={MCP_SERVER_NAME: mcp_registration()},
        path=(MCP_SERVER_KEY,),
    )


# Cursor's ``.mdc`` frontmatter. It must be the first bytes of the file (line 1),
# which is why Cursor is a whole-file target and not a managed block: no marker
# line can sit above the frontmatter. ``globs`` scopes the rule to Python files,
# since AGENTS.md (which Cursor reads natively) carries the always-on layer.
_CURSOR_FRONTMATTER = (
    "---\n"
    "description: Protean framework guidance for this project\n"
    'globs: "**/*.py"\n'
    "alwaysApply: false\n"
    "---\n"
)


def render_cursor_body(version: str) -> str:
    """Compose the whole ``.cursor/rules/protean.mdc`` file for *version*.

    Leads with the MDC frontmatter at line 1, then a version stamp comment, then
    the same composed guidance :func:`render_agents_body` builds. The stamp lives
    in the file itself, so a version bump changes the rendered content and ``dx
    check`` reports staleness. Deterministic for a given *version*, since
    :func:`render_agents_body` is.
    """
    stamp = f"<!-- protean:{version} -->"
    body = render_agents_body(version)
    return f"{_CURSOR_FRONTMATTER}{stamp}\n\n{body}\n"


def cursor_managed_file(version: str) -> ManagedWholeFile:
    """Return the whole-file request for the project's ``.cursor/rules/protean.mdc``.

    ``dx`` owns the whole file: MDC frontmatter must start at line 1, so there is
    no room for a managed-block marker above it. A hand edit anywhere in the file
    is a conflict.
    """
    return ManagedWholeFile(
        target=CURSOR_TARGET,
        version=version,
        body=render_cursor_body(version),
    )


def copilot_managed_file(version: str) -> ManagedBlock:
    """Return the managed block for the project's ``.github/copilot-instructions.md``.

    Same shape as AGENTS.md: the composed guidance in an HTML-comment managed
    block, so the file stays co-owned with the user's own Copilot instructions.
    """
    return _markdown_block(COPILOT_TARGET, version, render_agents_body(version))


def opencode_registration() -> dict[str, Any]:
    """Return opencode's launch shape for Protean's MCP server.

    opencode's config uses a different shape from ``.mcp.json``: a ``type`` of
    ``"local"``, ``command`` as an argv list, and an ``enabled`` flag. This is a
    fresh dict each call, so a caller cannot mutate a shared default.
    """
    return {"type": "local", "command": ["protean", "mcp"], "enabled": True}


def opencode_managed_file(version: str) -> ManagedJsonKeys:
    """Return the managed-JSON-keys request for the project's ``opencode.json``.

    Manages only the ``mcp.protean`` key-path, so an existing ``opencode.json``
    keeps every other opencode key and every other mcp server. The request
    carries *version* as its stamp so its state row advances in step with the
    other files on an upgrade. The registration itself is the same across
    versions.
    """
    return ManagedJsonKeys(
        target=OPENCODE_TARGET,
        version=version,
        data={OPENCODE_SERVER_NAME: opencode_registration()},
        path=(OPENCODE_MCP_KEY,),
    )


def managed_files(version: str) -> tuple[ManagedFile, ...]:
    """Return every managed file ``protean dx`` writes, in a stable order.

    The canonical set comes first: AGENTS.md, then the CLAUDE.md bridge that
    points at it, then the ``.mcp.json`` registration. The per-editor set follows:
    Cursor, Copilot, opencode. All six are stamped to *version*.
    """
    return (
        agents_managed_file(version),
        claude_bridge_managed_file(version),
        mcp_json_managed_file(version),
        cursor_managed_file(version),
        copilot_managed_file(version),
        opencode_managed_file(version),
    )
