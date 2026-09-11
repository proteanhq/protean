"""Tests for the ``protean dx`` file renderers."""

from __future__ import annotations

import pytest

from protean.dx.managed_files import ManagedBlock
from protean.dx.pack import PACK_VERSION, load_agents_source
from protean.dx.renderers import (
    AGENTS_TARGET,
    BLOCK_ID,
    CLAUDE_BRIDGE_BODY,
    CLAUDE_BRIDGE_TARGET,
    _strip_leading_h1,
    agents_managed_file,
    claude_bridge_managed_file,
    managed_files,
    render_agents_body,
)
from protean.ir.generators.agents import generate_agents_md

# The renderers are pure functions over package data and never touch a domain.
pytestmark = pytest.mark.no_test_domain


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


def test_managed_files_returns_agents_then_bridge() -> None:
    files = managed_files("0.18.0")

    assert [f.target for f in files] == ["AGENTS.md", "CLAUDE.md"]
    assert all(f.version == "0.18.0" for f in files)


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
