"""CLI tests for the ``protean dx`` command group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli.dx import app
from protean.dx.pack import PACK_VERSION
from protean.dx.renderers import REQUIRED_TARGETS

# The dx commands are pure filesystem work and never load a domain.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()


def _install(project: Path) -> None:
    """Install the dx files into *project* and assert it succeeded."""
    result = runner.invoke(app, ["install", "-p", str(project)])
    assert result.exit_code == 0, result.output


def _install_baseline(project: Path) -> None:
    """Write only the required baseline (AGENTS.md + CLAUDE.md), the scaffold shape.

    ``protean new`` writes exactly this set through the same renderers, so a
    baseline-only directory reproduces a freshly scaffolded project without
    driving the whole ``new`` flow.
    """
    from protean.dx import apply_managed_file
    from protean.dx.renderers import baseline_managed_files

    for managed_file in baseline_managed_files(PACK_VERSION):
        apply_managed_file(project, managed_file)


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


def test_install_writes_mcp_json_with_the_registration(tmp_path: Path) -> None:
    """AC1: install writes .mcp.json with the Protean MCP server registration."""
    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mcp = tmp_path / ".mcp.json"
    assert mcp.exists()
    data = json.loads(mcp.read_text(encoding="utf-8"))
    assert data == {"mcpServers": {"protean": {"command": "protean", "args": ["mcp"]}}}


def test_install_preserves_other_servers_in_mcp_json(tmp_path: Path) -> None:
    """AC2: an existing .mcp.json with another server keeps it and gains protean."""
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(
        json.dumps({"mcpServers": {"other": {"command": "run-other"}}}) + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = json.loads(mcp.read_text(encoding="utf-8"))
    # The user's server survived, and Protean's was added alongside it.
    assert data["mcpServers"]["other"] == {"command": "run-other"}
    assert data["mcpServers"]["protean"] == {"command": "protean", "args": ["mcp"]}


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
    """A --path that is not an existing directory is rejected the same way by all
    verbs: a regular file, and a missing (mistyped) path."""
    a_file = tmp_path / "afile"
    a_file.write_text("x", encoding="utf-8")
    missing = tmp_path / "does-not-exist"

    for bad_path in (a_file, missing):
        for verb in ("install", "refresh", "diff", "check"):
            result = runner.invoke(app, [verb, "-p", str(bad_path)])
            assert result.exit_code == 2, f"{verb} {bad_path}: {result.output}"
            # Flatten whitespace: rich wraps the line at the terminal width, and a
            # long temp path can split the message across a newline in CI.
            assert "not a directory" in " ".join(result.output.split())
    # A rejected path writes nothing.
    assert not missing.exists()


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
    # Each stale line names the region that target's merge mode owns: a block for
    # the Markdown files, the key-path for .mcp.json, which has no block at all.
    # Flatten whitespace: rich wraps the line at the terminal width.
    flat = " ".join(result.output.split())
    assert "update AGENTS.md — the managed block 'protean' is stale" in flat, flat
    assert "update .mcp.json — the managed key 'mcpServers.protean' is stale" in flat, (
        flat
    )
    # check writes nothing, even on a stale block.
    assert (tmp_path / "AGENTS.md").read_bytes() == agents_before
    assert _state_file(tmp_path).read_bytes() == state_before


def test_check_flags_a_drifted_mcp_json(tmp_path: Path) -> None:
    """AC3: after the managed entry is removed, check reports drift and exits 1."""
    _install(tmp_path)
    mcp = tmp_path / ".mcp.json"
    # The user deletes Protean's managed entry: check must flag the drift.
    mcp.write_text(json.dumps({"mcpServers": {}}) + "\n", encoding="utf-8")

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "Drift detected" in result.output
    assert ".mcp.json" in result.output


def test_check_flags_a_missing_mcp_json(tmp_path: Path) -> None:
    """A .mcp.json removed after install reads as drift (a pending create)."""
    _install(tmp_path)
    (tmp_path / ".mcp.json").unlink()

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert ".mcp.json" in result.output


def test_diff_previews_mcp_json_then_install_no_ops(tmp_path: Path) -> None:
    """diff previews the .mcp.json create; a second install is a no-op."""
    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert ".mcp.json" in result.output
    assert "+" in result.output  # a unified-diff addition line for the new file
    assert not (tmp_path / ".mcp.json").exists()  # diff wrote nothing

    _install(tmp_path)
    second = runner.invoke(app, ["install", "-p", str(tmp_path)])
    assert second.exit_code == 0, second.output
    # Every target reports up to date on the second install.
    assert "created" not in second.output


# --- check: the required-baseline split -------------------------------------


def test_check_passes_on_baseline_only(tmp_path: Path) -> None:
    """The scaffold shape (baseline present, no optional files) passes check."""
    _install_baseline(tmp_path)

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Up to date" in result.output
    # The optional files were never written and were not created by the check.
    for rel in (".mcp.json", _CURSOR_RULE, _COPILOT_FILE, _OPENCODE_CONFIG):
        assert not (tmp_path / rel).exists()


def test_check_ignores_a_never_installed_optional_file(tmp_path: Path) -> None:
    """An optional file the user never chose is not counted, nor even reported.

    check scans only the baseline plus already-installed optional targets, so a
    never-installed editor file is neither drift nor a scanned line.
    """
    _install_baseline(tmp_path)

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    for rel in (".mcp.json", _CURSOR_RULE, _COPILOT_FILE, _OPENCODE_CONFIG):
        assert rel not in flat, f"check must not scan the un-installed {rel}: {flat}"


def test_check_scopes_in_an_optional_file_present_on_disk(tmp_path: Path) -> None:
    """An optional file present on disk is verified, even with no state entry.

    A user who hand-wrote a bare .mcp.json (no managed entry, so nothing recorded
    in state) is telling check they want that file managed. check scopes it in and
    flags the missing registration.
    """
    _install_baseline(tmp_path)
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {}}) + "\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "Drift detected" in result.output
    assert ".mcp.json" in result.output
    # Only the on-disk .mcp.json is scoped in. The other optional files are absent
    # on disk and unrecorded, so check skips them. The old "scan all six" code
    # would have listed each as "not installed yet".
    flat = " ".join(result.output.split())
    for rel in (_CURSOR_RULE, _COPILOT_FILE, _OPENCODE_CONFIG):
        assert rel not in flat, f"check must not scan the un-installed {rel}: {flat}"


@pytest.mark.parametrize("required", sorted(REQUIRED_TARGETS))
def test_check_flags_each_required_file_on_its_own(
    tmp_path: Path, required: str
) -> None:
    """Every required file is verified on its own, not only as a pair.

    Deleting one and leaving the other in place must still fail the check. With
    both deleted at once (test_check_fails_on_fresh_dir), a target dropped from
    REQUIRED_TARGETS by mistake would still look covered: the other one carries
    the assertion. Parametrized over the constant, so a target added to the
    baseline gets this case for free.
    """
    _install_baseline(tmp_path)
    (tmp_path / required).unlink()

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "Drift detected" in result.output
    # Flatten whitespace: rich wraps the line at the terminal width.
    flat = " ".join(result.output.split())
    assert f"create {required} — not installed yet" in flat, flat
    # Scope is unchanged by the deletion: the optional files stay out.
    for rel in (".mcp.json", _CURSOR_RULE, _COPILOT_FILE, _OPENCODE_CONFIG):
        assert rel not in flat, f"check must not scan the un-installed {rel}: {flat}"


def test_check_scopes_in_a_dangling_symlink_at_an_optional_target(
    tmp_path: Path,
) -> None:
    """A dangling symlink at an unrecorded optional target is an error, not a skip.

    ``Path.exists`` reads a dangling symlink as absent, so a scope probe on
    ``exists`` alone would skip the target and let check exit 0 over a symlink dx
    refuses to write through. The scope counts any symlink as present, so the
    per-file diff reaches its refusal and reports it.
    """
    _install_baseline(tmp_path)
    (tmp_path / ".mcp.json").symlink_to(tmp_path / "nowhere.json")

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    flat = " ".join(result.output.split())
    assert "error .mcp.json" in flat, flat
    assert "symlink" in flat, flat


def test_diff_still_previews_all_six_on_baseline_only(tmp_path: Path) -> None:
    """diff is unscoped: on a baseline-only project it still previews the optional
    files as pending creates, where check ignores them."""
    _install_baseline(tmp_path)

    result = runner.invoke(app, ["diff", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    for rel in (".mcp.json", _CURSOR_RULE, _COPILOT_FILE, _OPENCODE_CONFIG):
        assert rel in result.output, f"diff must still preview {rel}"
    # Flatten whitespace: rich wraps the line at the terminal width.
    assert "not installed yet" in " ".join(result.output.split())


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
    # A conflict is not fixed by re-installing, so check tells the user to resolve
    # it first rather than to just run install. Flatten for rich line wrapping.
    assert "Resolve the conflicts" in " ".join(check_result.output.split())

    install_result = runner.invoke(app, ["install", "-p", str(tmp_path)])
    assert install_result.exit_code == 1, install_result.output
    assert "conflict" in install_result.output
    # The write was refused, so the hand-edited content is untouched.
    assert agents.read_text(encoding="utf-8") == edited
    # A conflict on one file does not stop the others: CLAUDE.md still applied.
    assert "CLAUDE.md" in install_result.output


def test_mcp_json_conflict_names_the_key_path_not_a_block(tmp_path: Path) -> None:
    """A .mcp.json conflict points at mcpServers.protean, not at a managed block.

    The JSON target has no marked block, so reporting one would send the user
    looking for a Markdown region the file does not have.
    """
    _install(tmp_path)
    mcp = tmp_path / ".mcp.json"
    data = json.loads(mcp.read_text(encoding="utf-8"))
    # A hand edit inside Protean's own entry: the managed key now differs from
    # both what the writer wrote and what the render wants.
    data["mcpServers"]["protean"] = {"command": "my-own-protean"}
    mcp.write_text(json.dumps(data) + "\n", encoding="utf-8")

    for verb in ("check", "install"):
        result = runner.invoke(app, [verb, "-p", str(tmp_path)])
        assert result.exit_code == 1, f"{verb}: {result.output}"
        # Flatten whitespace: rich wraps the line at the terminal width.
        flat = " ".join(result.output.split())
        assert "the managed key 'mcpServers.protean'" in flat, flat
        assert "managed block" not in flat, flat

    # The write was refused, so the hand edit survived.
    assert json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]["protean"] == {
        "command": "my-own-protean"
    }


def test_edits_outside_the_managed_keys_are_reported_as_keys(tmp_path: Path) -> None:
    """Another server added to .mcp.json reads as an edit outside the managed keys."""
    _install(tmp_path)
    mcp = tmp_path / ".mcp.json"
    data = json.loads(mcp.read_text(encoding="utf-8"))
    data["mcpServers"]["other"] = {"command": "run-other"}
    mcp.write_text(json.dumps(data) + "\n", encoding="utf-8")

    check_result = runner.invoke(app, ["check", "-p", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output
    assert "edited outside the managed keys" in " ".join(check_result.output.split())

    install_result = runner.invoke(app, ["install", "-p", str(tmp_path)])
    assert install_result.exit_code == 0, install_result.output
    flat = " ".join(install_result.output.split())
    assert "your edits outside the managed keys were kept" in flat, flat
    assert json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]["other"] == {
        "command": "run-other"
    }


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
    # Flatten whitespace: rich wraps the line at the terminal width.
    assert "edited around the block" in " ".join(result.output.split())


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
    """A malformed state file is a clean error naming the state file, not a trace.

    On a baseline-only project the scope read of the state file runs first, so a
    corrupt file is attributed to ``.protean/dx-state.json`` and the scan stops
    before the per-file loop. If the early scope read were dropped, the loop would
    instead hit ``AGENTS.md``'s own ``load_state`` and name ``AGENTS.md``, so
    asserting the state file (and not ``AGENTS.md``) pins the early return.
    """
    _install_baseline(tmp_path)
    _state_file(tmp_path).write_text("{ not json", encoding="utf-8")

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    flat = " ".join(result.output.split())
    assert "error" in flat, flat
    assert ".protean/dx-state.json" in flat, flat
    # The scan stopped at the scope read and never reached the per-file loop.
    assert "AGENTS.md" not in flat, flat


def test_symlinked_state_file_fails_loud(tmp_path: Path) -> None:
    """A symlinked state file is refused as a clean error (the ManagedFileError arm).

    The scope read calls ``load_state``, which refuses to follow a symlinked state
    path and raises ``ManagedFileError`` (not the ``ValueError`` a corrupt file
    raises). check surfaces it as exit 2 naming the state file.
    """
    _install_baseline(tmp_path)
    state = _state_file(tmp_path)
    real = tmp_path / "elsewhere.json"
    real.write_text(state.read_text(encoding="utf-8"), encoding="utf-8")
    state.unlink()
    state.symlink_to(real)

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 2, result.output
    flat = " ".join(result.output.split())
    assert "error" in flat, flat
    assert ".protean/dx-state.json" in flat, flat


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


# --- per-editor files -------------------------------------------------------

_CURSOR_RULE = ".cursor/rules/protean.mdc"
_COPILOT_FILE = ".github/copilot-instructions.md"
_OPENCODE_CONFIG = "opencode.json"


def test_install_writes_all_six_files(tmp_path: Path) -> None:
    """AC1: install writes the three per-editor files alongside the canonical set."""
    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    for rel in (
        "AGENTS.md",
        "CLAUDE.md",
        ".mcp.json",
        _CURSOR_RULE,
        _COPILOT_FILE,
        _OPENCODE_CONFIG,
    ):
        assert (tmp_path / rel).exists(), f"{rel} was not written"

    # Cursor's rule starts with the MDC frontmatter at line 1 and carries the stamp.
    cursor = (tmp_path / _CURSOR_RULE).read_text(encoding="utf-8")
    assert cursor.startswith("---\n")
    assert 'globs: "**/*.py"' in cursor
    assert PACK_VERSION in cursor
    assert "## Do not break these rules" in cursor

    # Copilot's file carries the guidance in the managed block.
    copilot = (tmp_path / _COPILOT_FILE).read_text(encoding="utf-8")
    assert "<!-- PROTEAN:BEGIN protean -->" in copilot
    assert "## Do not break these rules" in copilot

    # opencode's config carries its own launch shape under mcp.protean.
    opencode = json.loads((tmp_path / _OPENCODE_CONFIG).read_text(encoding="utf-8"))
    assert opencode == {
        "mcp": {
            "protean": {"type": "local", "command": ["protean", "mcp"], "enabled": True}
        }
    }


def test_second_install_is_idempotent_across_all_files(tmp_path: Path) -> None:
    """AC2 (first half): a second install is a no-op for every file, exit 0."""
    _install(tmp_path)
    before = {
        rel: (tmp_path / rel).read_bytes()
        for rel in (
            "AGENTS.md",
            "CLAUDE.md",
            ".mcp.json",
            _CURSOR_RULE,
            _COPILOT_FILE,
            _OPENCODE_CONFIG,
        )
    }

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "created" not in result.output  # nothing new; every file already up to date
    for rel, content in before.items():
        assert (tmp_path / rel).read_bytes() == content, f"{rel} changed on re-install"


def test_check_passes_on_a_fresh_install_of_all_files(tmp_path: Path) -> None:
    _install(tmp_path)
    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Up to date" in result.output


def test_install_preserves_other_keys_in_opencode_json(tmp_path: Path) -> None:
    """An existing opencode.json keeps the user's own keys and other mcp servers."""
    opencode = tmp_path / _OPENCODE_CONFIG
    opencode.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcp": {"other": {"type": "local", "command": ["run-other"]}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = json.loads(opencode.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"  # unrelated top-level key survived
    assert data["mcp"]["other"] == {"type": "local", "command": ["run-other"]}
    assert data["mcp"]["protean"] == {
        "type": "local",
        "command": ["protean", "mcp"],
        "enabled": True,
    }


def test_install_keeps_user_prose_around_the_copilot_block(tmp_path: Path) -> None:
    """Copilot's file is co-owned: the user's own instructions survive a refresh."""
    _install(tmp_path)
    copilot = tmp_path / _COPILOT_FILE
    copilot.write_text(
        "# My Copilot rules\nkeep me\n" + copilot.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["install", "-p", str(tmp_path)])

    assert result.exit_code == 0, result.output
    text = copilot.read_text(encoding="utf-8")
    assert "# My Copilot rules" in text
    assert "keep me" in text
    assert "<!-- PROTEAN:BEGIN protean -->" in text


def test_check_flags_a_drifted_cursor_rule(tmp_path: Path) -> None:
    """AC2: a hand-edited Cursor rule fails check, naming the whole file as owned."""
    _install(tmp_path)
    cursor = tmp_path / _CURSOR_RULE
    cursor.write_text(
        cursor.read_text(encoding="utf-8") + "\nHAND EDIT\n", encoding="utf-8"
    )
    edited = cursor.read_text(encoding="utf-8")

    check_result = runner.invoke(app, ["check", "-p", str(tmp_path)])
    assert check_result.exit_code == 1, check_result.output
    flat = " ".join(check_result.output.split())
    assert "conflict" in flat
    assert _CURSOR_RULE in flat, flat
    assert "the whole file" in flat, flat

    # install refuses the hand-edited whole file and leaves it in place.
    install_result = runner.invoke(app, ["install", "-p", str(tmp_path)])
    assert install_result.exit_code == 1, install_result.output
    assert cursor.read_text(encoding="utf-8") == edited


def test_check_flags_a_drifted_copilot_block(tmp_path: Path) -> None:
    """AC2: an in-block edit to the Copilot file fails check as a conflict."""
    _install(tmp_path)
    copilot = tmp_path / _COPILOT_FILE
    copilot.write_text(
        copilot.read_text(encoding="utf-8").replace(
            "# Protean agent guidance", "# Hand edited heading", 1
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    flat = " ".join(result.output.split())
    assert "conflict" in flat
    assert _COPILOT_FILE in flat
    assert "the managed block 'protean'" in flat, flat
    assert "the whole file" not in flat, flat


def test_check_flags_a_drifted_opencode_config(tmp_path: Path) -> None:
    """AC2: editing opencode's managed mcp.protean entry fails check."""
    _install(tmp_path)
    opencode = tmp_path / _OPENCODE_CONFIG
    data = json.loads(opencode.read_text(encoding="utf-8"))
    data["mcp"]["protean"] = {"type": "local", "command": ["my-own"]}
    opencode.write_text(json.dumps(data) + "\n", encoding="utf-8")

    result = runner.invoke(app, ["check", "-p", str(tmp_path)])

    assert result.exit_code == 1, result.output
    flat = " ".join(result.output.split())
    assert "the managed key 'mcp.protean'" in flat, flat
    assert "managed block" not in flat, flat
