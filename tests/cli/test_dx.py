"""CLI tests for the ``protean dx`` command group."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli.dx import app
from protean.dx.pack import PACK_VERSION

# The dx commands are pure filesystem work and never load a domain.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()


def _install(project: Path) -> None:
    """Install the dx files into *project* and assert it succeeded."""
    result = runner.invoke(app, ["install", "-p", str(project)])
    assert result.exit_code == 0, result.output


def _state_file(project: Path) -> Path:
    return project / ".protean" / "dx-state.json"


# --- no args / help ---------------------------------------------------------


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 2


def test_help_lists_the_verbs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for verb in ("install", "refresh", "diff", "check"):
        assert verb in result.output


# --- install ----------------------------------------------------------------


def test_install_writes_both_files_and_state(tmp_path: Path) -> None:
    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "created" in result.output

    agents = tmp_path / "AGENTS.md"
    claude = tmp_path / "CLAUDE.md"
    assert agents.exists()
    assert claude.exists()
    assert _state_file(tmp_path).exists()

    agents_text = agents.read_text(encoding="utf-8")
    assert "<!-- PROTEAN:BEGIN protean -->" in agents_text
    assert "<!-- PROTEAN:END protean -->" in agents_text
    assert PACK_VERSION in agents_text
    assert "## Do not break these rules" in agents_text

    claude_text = claude.read_text(encoding="utf-8")
    assert claude_text == (
        "<!-- PROTEAN:BEGIN protean -->\n@AGENTS.md\n<!-- PROTEAN:END protean -->\n"
    )


def test_install_is_idempotent(tmp_path: Path) -> None:
    _install(tmp_path)
    first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "already up to date" in result.output
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first


def test_install_defaults_to_the_current_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "AGENTS.md").exists()


# --- refresh ----------------------------------------------------------------


def test_refresh_creates_when_missing(tmp_path: Path) -> None:
    """Refresh is the same idempotent apply, so it also creates a missing file."""
    result = runner.invoke(app, ["refresh", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "AGENTS.md").exists()


def test_refresh_rewrites_a_stale_block_and_keeps_user_edits(
    tmp_path: Path, monkeypatch
) -> None:
    """A version bump makes the block stale; refresh rewrites it to the new stamp
    and preserves the user's edits around the block."""
    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.9")
    _install(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8") + "\n## User notes\nkeep me\n",
        encoding="utf-8",
    )
    assert "9.9.9" in agents.read_text(encoding="utf-8")

    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.10")
    result = runner.invoke(app, ["refresh", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "updated" in result.output
    assert "kept" in result.output
    text = agents.read_text(encoding="utf-8")
    assert "9.9.10" in text
    assert "9.9.9" not in text
    # The user's content around the block survived the rewrite.
    assert "## User notes" in text
    assert "keep me" in text


# --- diff -------------------------------------------------------------------


def test_diff_on_fresh_dir_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "create" in result.output
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".protean").exists()


def test_diff_reports_up_to_date_after_install(tmp_path: Path) -> None:
    _install(tmp_path)
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output


def test_diff_shows_a_unified_diff_on_a_fresh_project(tmp_path: Path) -> None:
    """diff prints an actual unified diff, not just a status line, and writes nothing."""
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "--- AGENTS.md (current)" in result.output
    assert "+++ AGENTS.md (managed)" in result.output
    assert "+# Protean agent guidance" in result.output
    # The CLAUDE.md bridge body shows as an addition too.
    assert "+@AGENTS.md" in result.output
    # Still a read-only preview.
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_diff_shows_only_the_changed_line_on_a_stale_block(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.9")
    _install(tmp_path)

    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.10")
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "-# Protean agent guidance (9.9.9)" in result.output
    assert "+# Protean agent guidance (9.9.10)" in result.output


def test_diff_prints_no_diff_body_when_up_to_date(tmp_path: Path) -> None:
    _install(tmp_path)
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
    # No unified-diff hunk header when nothing would change.
    assert "@@" not in result.output


def test_non_directory_path_is_rejected_by_every_verb(tmp_path: Path) -> None:
    """A --path pointing at a regular file is rejected the same way by all verbs."""
    a_file = tmp_path / "afile"
    a_file.write_text("x", encoding="utf-8")

    for verb in ("install", "refresh", "diff", "check"):
        result = runner.invoke(app, [verb, "-p", str(a_file)])
        assert result.exit_code == 2, f"{verb}: {result.output}"
        assert "not a directory" in result.output


def test_diff_writes_nothing_on_a_stale_block(tmp_path: Path, monkeypatch) -> None:
    """diff computes the merged content on the UPDATE path but must not persist it."""
    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.9")
    _install(tmp_path)
    agents_before = (tmp_path / "AGENTS.md").read_bytes()
    state_before = _state_file(tmp_path).read_bytes()

    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.10")
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "update" in result.output
    assert (tmp_path / "AGENTS.md").read_bytes() == agents_before
    assert _state_file(tmp_path).read_bytes() == state_before


# --- check ------------------------------------------------------------------


def test_check_fails_on_fresh_dir(tmp_path: Path) -> None:
    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "Drift detected" in result.output
    assert not (tmp_path / "AGENTS.md").exists()


def test_check_passes_after_install(tmp_path: Path) -> None:
    _install(tmp_path)
    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Up to date" in result.output


def test_check_fails_when_the_version_advances(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.9")
    _install(tmp_path)
    agents_before = (tmp_path / "AGENTS.md").read_bytes()
    state_before = _state_file(tmp_path).read_bytes()

    monkeypatch.setattr("protean.dx.pack.PACK_VERSION", "9.9.10")
    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "update" in result.output
    # check writes nothing, even on a stale block.
    assert (tmp_path / "AGENTS.md").read_bytes() == agents_before
    assert _state_file(tmp_path).read_bytes() == state_before


# --- conflict ---------------------------------------------------------------


def test_hand_edit_inside_the_block_conflicts(tmp_path: Path) -> None:
    _install(tmp_path)
    agents = tmp_path / "AGENTS.md"
    # Edit the H1 the renderer itself emits inside the block, so the test does not
    # depend on the packaged pack's own headings.
    edited = agents.read_text(encoding="utf-8").replace(
        "# Protean agent guidance", "# Hand edited heading", 1
    )
    agents.write_text(edited, encoding="utf-8")

    check_result = runner.invoke(app, ["check", "-p", str(tmp_path)])
    assert check_result.exit_code == 1, check_result.output
    assert "conflict" in check_result.output

    install_result = runner.invoke(app, ["install", "-p", str(tmp_path)])
    assert install_result.exit_code == 1, install_result.output
    assert "conflict" in install_result.output
    # The write was refused, so the hand-edited content is untouched.
    assert agents.read_text(encoding="utf-8") == edited
    # A conflict on one file does not stop the others: CLAUDE.md still applied.
    assert "CLAUDE.md" in install_result.output


# --- edits around the block -------------------------------------------------


def test_edits_around_the_block_are_kept(tmp_path: Path) -> None:
    _install(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + "\n## My notes\nhello\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "kept" in result.output
    assert "## My notes" in claude.read_text(encoding="utf-8")


def test_check_notes_edits_around_the_block(tmp_path: Path) -> None:
    _install(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(
        claude.read_text(encoding="utf-8") + "\nuser line\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "edited around the block" in result.output


# --- filesystem errors ------------------------------------------------------


def test_unreadable_target_reports_an_error(tmp_path: Path) -> None:
    # A directory where a file is expected makes the target unreadable.
    (tmp_path / "AGENTS.md").mkdir()

    for verb in ("diff", "check", "install"):
        result = runner.invoke(app, [verb, "-p", str(tmp_path)])
        assert result.exit_code == 2, f"{verb}: {result.output}"
        assert "error" in result.output


def test_install_refuses_a_preexisting_agents_without_markers(tmp_path: Path) -> None:
    """A hand-written AGENTS.md with no PROTEAN markers is refused, not overwritten."""
    agents = tmp_path / "AGENTS.md"
    original = "# My own AGENTS\n\nHand-written notes.\n"
    agents.write_text(original, encoding="utf-8")

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    assert "error" in result.output
    # The user's file is left byte-for-byte intact.
    assert agents.read_text(encoding="utf-8") == original
    # A refusal on one file does not stop the others: CLAUDE.md is still created.
    assert (tmp_path / "CLAUDE.md").exists()


def test_install_error_outranks_conflict(tmp_path: Path) -> None:
    """When one target errors and another conflicts, install exits 2 (error wins)."""
    _install(tmp_path)
    # Conflict on AGENTS.md: hand-edit inside its managed block.
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "# Protean agent guidance", "# Hand edited", 1
        ),
        encoding="utf-8",
    )
    # Error on CLAUDE.md: replace it with a directory so it cannot be read.
    claude = tmp_path / "CLAUDE.md"
    claude.unlink()
    claude.mkdir()

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    assert "conflict" in result.output
    assert "error" in result.output


def test_corrupt_state_file_fails_loud(tmp_path: Path) -> None:
    """A malformed state file is surfaced as a clean error, not a traceback."""
    _install(tmp_path)
    _state_file(tmp_path).write_text("{ not json", encoding="utf-8")

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    assert "error" in result.output


def test_render_failure_reports_a_clean_error(tmp_path: Path, monkeypatch) -> None:
    """A pack that cannot render exits 2 with a message, not a raw traceback."""

    def _boom(_version: str) -> tuple:
        raise RuntimeError("pack data missing")

    monkeypatch.setattr("protean.dx.renderers.managed_files", _boom)

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    assert "error" in result.output
    assert "could not render" in result.output
    # Nothing was written: the render failed before any target was touched.
    assert not (tmp_path / "AGENTS.md").exists()
