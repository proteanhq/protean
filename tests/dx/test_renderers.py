"""Tests for the ``protean dx`` file renderers."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from protean.dx.managed_files import ManagedBlock, ManagedJsonKeys, ManagedWholeFile
from protean.dx.pack import PACK_VERSION, load_agents_source
from protean.dx.renderers import (
    AGENTS_TARGET,
    BLOCK_ID,
    CLAUDE_BRIDGE_BODY,
    CLAUDE_BRIDGE_TARGET,
    COPILOT_TARGET,
    CURSOR_TARGET,
    MCP_SERVER_KEY,
    MCP_SERVER_NAME,
    MCP_TARGET,
    OPENCODE_MCP_KEY,
    OPENCODE_SERVER_NAME,
    OPENCODE_TARGET,
    REQUIRED_TARGETS,
    _strip_leading_h1,
    agents_managed_file,
    baseline_managed_files,
    claude_bridge_managed_file,
    copilot_managed_file,
    cursor_managed_file,
    managed_files,
    mcp_json_managed_file,
    opencode_managed_file,
    opencode_registration,
    render_agents_body,
    render_cursor_body,
)
from protean.ir.generators.agents import generate_agents_md
from protean.mcp import mcp_registration

# The renderers are pure functions over package data and never touch a domain.
pytestmark = pytest.mark.no_test_domain

# Repo root: tests/dx/test_renderers.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _h1_lines(text: str) -> list[str]:
    """Return every top-level (``# ``) heading line in *text*."""
    return [line for line in text.split("\n") if line.startswith("# ")]


def test_agents_body_has_exactly_one_h1_stamped_with_the_version() -> None:
    body = render_agents_body("1.2.3")

    headings = _h1_lines(body)
    assert headings == ["# Protean agent guidance (1.2.3)"]
    assert body.startswith("# Protean agent guidance (1.2.3)\n")


def test_agents_body_composes_both_layers() -> None:
    """The body carries the pack's positive guidance and the diagnostics rules."""
    body = render_agents_body(PACK_VERSION)

    # The positive-guidance layer from the packaged AGENTS.md source.
    assert "## Working with Protean" in body
    # The negative hard-rules layer from the diagnostics registry, each rule
    # ending with its diagnostic code in backticks.
    assert "## Do not break these rules" in body
    code_anchors = [line for line in body.split("\n") if line.rstrip().endswith("`)")]
    assert len(code_anchors) > 0, "expected at least one diagnostic-code rule"
    for line in code_anchors:
        assert line.startswith("- **Do not**")


def test_source_fragments_each_have_at_most_one_h1() -> None:
    """The composed body is single-H1 only if each fragment brings at most one.

    ``_strip_leading_h1`` removes just the first H1 of each fragment, so a second
    H1 deeper in either fragment would leak into the composed file. Guard the
    assumption here so a future pack or registry change that adds one fails.
    """
    for fragment in (load_agents_source(), generate_agents_md(version="0.18.0")):
        assert len(_h1_lines(fragment)) <= 1


def test_agents_body_is_deterministic_for_a_version() -> None:
    assert render_agents_body("0.18.0") == render_agents_body("0.18.0")


def test_agents_body_changes_with_the_version() -> None:
    """A version bump changes the body, so a refresh detects and rewrites it."""
    assert render_agents_body("0.18.0") != render_agents_body("0.19.0")


def test_agents_managed_file_shape() -> None:
    managed = agents_managed_file("0.18.0")

    assert isinstance(managed, ManagedBlock)
    assert managed.target == AGENTS_TARGET == "AGENTS.md"
    assert managed.block_id == BLOCK_ID == "protean"
    assert managed.version == "0.18.0"
    assert managed.comment_prefix == "<!-- "
    assert managed.comment_suffix == " -->"
    assert managed.body == render_agents_body("0.18.0")


def test_claude_bridge_is_the_one_line_pointer() -> None:
    managed = claude_bridge_managed_file("0.18.0")

    assert isinstance(managed, ManagedBlock)
    assert managed.target == CLAUDE_BRIDGE_TARGET == "CLAUDE.md"
    assert managed.body == CLAUDE_BRIDGE_BODY == "@AGENTS.md"
    assert managed.version == "0.18.0"


def test_claude_bridge_body_is_version_independent() -> None:
    """Only the stamp moves with the version; the one-line body never churns."""
    assert (
        claude_bridge_managed_file("0.18.0").body
        == claude_bridge_managed_file("0.19.0").body
    )


def test_mcp_json_managed_file_shape() -> None:
    managed = mcp_json_managed_file("0.18.0")

    assert isinstance(managed, ManagedJsonKeys)
    assert managed.target == MCP_TARGET == ".mcp.json"
    assert managed.version == "0.18.0"
    assert managed.path == (MCP_SERVER_KEY,) == ("mcpServers",)
    assert managed.managed_keys == (MCP_SERVER_NAME,) == ("protean",)
    # The value under the managed key is the single-sourced registration shape.
    assert managed.data[MCP_SERVER_NAME] == mcp_registration()
    assert managed.data["protean"] == {"command": "protean", "args": ["mcp"]}


def test_mcp_registration_imports_without_the_mcp_extra() -> None:
    """The renderer runs on every ``dx install``, so its registration source must
    import without the optional ``mcp`` SDK.

    Run a subprocess whose import system refuses the ``mcp`` package, then import
    ``protean.mcp`` and call ``mcp_registration``. If the helper reached for the
    SDK, the import would fail; that it returns the launch shape proves it does
    not, and that ``mcp`` never lands in ``sys.modules`` proves nothing pulled it
    in transitively.
    """
    code = (
        "import sys, importlib.abc\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name == 'mcp' or name.startswith('mcp.'):\n"
        "            raise ImportError('mcp extra blocked for this test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Block())\n"
        "from protean.mcp import mcp_registration\n"
        "assert mcp_registration() == {'command': 'protean', 'args': ['mcp']}\n"
        "assert 'mcp' not in sys.modules\n"
        "print('sdk-free-ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "sdk-free-ok" in result.stdout


def test_baseline_is_every_required_target_in_managed_files_order() -> None:
    """The scaffold's baseline is REQUIRED_TARGETS, read from managed_files.

    protean new writes this set and protean dx check requires it, so the two read
    the same list. AGENTS.md comes before the CLAUDE.md bridge that points at it.
    """
    baseline = baseline_managed_files("0.18.0")

    assert [f.target for f in baseline] == ["AGENTS.md", "CLAUDE.md"]
    assert {f.target for f in baseline} == set(REQUIRED_TARGETS)
    assert all(f.version == "0.18.0" for f in baseline)
    # Byte-identical to what a dx install writes for those targets.
    rendered = {f.target: f for f in managed_files("0.18.0")}
    assert all(f == rendered[f.target] for f in baseline)


def test_baseline_rejects_a_required_target_with_no_renderer(monkeypatch) -> None:
    """A required target no renderer produces is a loud failure, not a short list.

    Silently returning the shorter set would let protean new write a project that
    fails its own protean dx check, which is the drift this baseline exists to
    prevent.
    """
    monkeypatch.setattr(
        "protean.dx.renderers.REQUIRED_TARGETS",
        frozenset({AGENTS_TARGET, CLAUDE_BRIDGE_TARGET, "GEMINI.md"}),
    )

    with pytest.raises(ValueError, match="GEMINI.md"):
        baseline_managed_files("0.18.0")


def test_managed_files_returns_canonical_then_per_editor() -> None:
    files = managed_files("0.18.0")

    assert [f.target for f in files] == [
        "AGENTS.md",
        "CLAUDE.md",
        ".mcp.json",
        ".cursor/rules/protean.mdc",
        ".github/copilot-instructions.md",
        "opencode.json",
    ]
    assert all(f.version == "0.18.0" for f in files)


# --- Cursor -----------------------------------------------------------------


def test_cursor_body_starts_with_the_mdc_frontmatter() -> None:
    """The MDC frontmatter must be the first bytes: Cursor parses it at line 1."""
    body = render_cursor_body("0.18.0")

    assert body.startswith(
        "---\n"
        "description: Protean framework guidance for this project\n"
        'globs: "**/*.py"\n'
        "alwaysApply: false\n"
        "---\n"
    )


def test_cursor_body_stamps_the_version_and_carries_the_guidance() -> None:
    body = render_cursor_body("0.18.0")

    assert "<!-- protean:0.18.0 -->" in body
    # The composed guidance follows the frontmatter and stamp.
    assert render_agents_body("0.18.0") in body
    assert "## Do not break these rules" in body


def test_cursor_body_changes_with_the_version() -> None:
    """A version bump changes the whole file, so a refresh detects staleness."""
    assert render_cursor_body("0.18.0") != render_cursor_body("0.19.0")


def test_cursor_managed_file_is_a_whole_file_target() -> None:
    managed = cursor_managed_file("0.18.0")

    assert isinstance(managed, ManagedWholeFile)
    assert managed.target == CURSOR_TARGET == ".cursor/rules/protean.mdc"
    assert managed.version == "0.18.0"
    assert managed.body.startswith("---\n")  # MDC frontmatter at line 1
    assert "<!-- protean:0.18.0 -->" in managed.body
    assert "## Do not break these rules" in managed.body


# --- Copilot ----------------------------------------------------------------


def test_copilot_managed_file_is_a_block_with_the_guidance() -> None:
    managed = copilot_managed_file("0.18.0")

    assert isinstance(managed, ManagedBlock)
    assert managed.target == COPILOT_TARGET == ".github/copilot-instructions.md"
    assert managed.block_id == BLOCK_ID == "protean"
    assert managed.version == "0.18.0"
    assert managed.comment_prefix == "<!-- "
    assert managed.comment_suffix == " -->"
    assert "## Do not break these rules" in managed.body  # composed guidance


# --- opencode ---------------------------------------------------------------


def test_opencode_registration_is_the_local_launch_shape() -> None:
    """opencode's shape differs from ``.mcp.json``: type/command-list/enabled."""
    assert opencode_registration() == {
        "type": "local",
        "command": ["protean", "mcp"],
        "enabled": True,
    }


def test_opencode_registration_is_a_fresh_dict_each_call() -> None:
    first = opencode_registration()
    first["command"].append("mutated")
    assert opencode_registration()["command"] == ["protean", "mcp"]


def test_opencode_managed_file_shape() -> None:
    managed = opencode_managed_file("0.18.0")

    assert isinstance(managed, ManagedJsonKeys)
    assert managed.target == OPENCODE_TARGET == "opencode.json"
    assert managed.version == "0.18.0"
    assert managed.path == (OPENCODE_MCP_KEY,) == ("mcp",)
    assert managed.managed_keys == (OPENCODE_SERVER_NAME,) == ("protean",)
    assert managed.data[OPENCODE_SERVER_NAME] == {
        "type": "local",
        "command": ["protean", "mcp"],
        "enabled": True,
    }


def test_opencode_shape_differs_from_mcp_json() -> None:
    """The two JSON targets carry different registration shapes and key-paths."""
    opencode = opencode_managed_file("0.18.0")
    mcp = mcp_json_managed_file("0.18.0")

    assert opencode.path != mcp.path
    assert opencode.data["protean"] != mcp.data["protean"]


# --- _strip_leading_h1 ------------------------------------------------------


def test_strip_leading_h1_drops_the_heading_and_one_blank_line() -> None:
    assert _strip_leading_h1("# Title\n\nbody\n") == "body\n"


def test_strip_leading_h1_without_trailing_blank() -> None:
    assert _strip_leading_h1("# Title\nbody") == "body"


def test_strip_leading_h1_finds_the_h1_past_leading_blank_lines() -> None:
    # Leading blanks are left for the caller to strip; only the H1 line and one
    # blank after it are removed.
    assert _strip_leading_h1("\n\n# Title\n\nbody") == "\n\nbody"


def test_strip_leading_h1_leaves_text_without_an_h1_unchanged() -> None:
    text = "no heading here\nsecond line\n"
    assert _strip_leading_h1(text) == text


def test_strip_leading_h1_does_not_touch_an_h2() -> None:
    text = "## Subheading\nbody\n"
    assert _strip_leading_h1(text) == text


def test_repo_mcp_json_matches_what_the_renderer_writes() -> None:
    """The repository's own ``.mcp.json`` carries the shape ``dx install`` writes.

    The repo ships a ``.mcp.json`` and the MCP docs print one by hand. If either
    drifts from the renderer, a user gets two contradictory registration formats
    and a client reading one of them never finds the server. Pin all three to the
    same key-path and value here.
    """
    repo_mcp_json = json.loads((_REPO_ROOT / MCP_TARGET).read_text(encoding="utf-8"))

    assert repo_mcp_json[MCP_SERVER_KEY][MCP_SERVER_NAME] == mcp_registration()


def test_mcp_docs_snippet_matches_what_the_renderer_writes() -> None:
    """The hand-written snippet in the MCP reference matches the renderer too."""
    page = (_REPO_ROOT / "docs/reference/cli/runtime/mcp.md").read_text(
        encoding="utf-8"
    )
    snippets = re.findall(r"```json\n(.*?)```", page, flags=re.DOTALL)
    registrations = [
        json.loads(snippet)
        for snippet in snippets
        if MCP_SERVER_KEY in json.loads(snippet)
    ]

    assert registrations, "the MCP reference no longer prints a registration snippet"
    for registration in registrations:
        assert registration[MCP_SERVER_KEY][MCP_SERVER_NAME] == mcp_registration()
