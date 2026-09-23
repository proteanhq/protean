"""Tests for the Claude Code plugin renderer and the ``dx build-plugin`` verb."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import protean
from protean.cli.dx import app
from protean.dx.pack import (
    PACK_VERSION,
    SKILL_FILE,
    SKILLS_DIR,
    iter_skills,
    pack_files,
)
from protean.dx.plugin import (
    MARKETPLACE_PATH,
    PLUGIN_MANIFEST_PATH,
    PLUGIN_NAME,
    PLUGIN_ROOT,
    PLUGIN_SKILLS_ROOT,
    PLUGIN_SOURCE,
    _prune_empty_dirs,
    marketplace_manifest,
    plugin_drift,
    plugin_manifest,
    render_plugin_files,
    write_plugin,
)

# The renderer is pure work over package data and the CLI verbs never load a
# domain.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()

# Repo root: tests/dx/test_plugin.py -> parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _flat(output: str) -> str:
    """Return CLI output with newlines removed, so a width-wrapped line matches.

    Click and Rich wrap output to the terminal width, so an assertion on a phrase
    that Rich may split across lines has to compare width-independently.
    """
    return output.replace("\n", "")


# --- the committed tree (the drift guard) -----------------------------------


def test_repo_plugin_tree_matches_the_render() -> None:
    """The committed plugin tree carries exactly what the renderer writes.

    This is the analogue of ``test_repo_mcp_json_matches_what_the_renderer_writes``
    for the plugin tree: if the committed ``.claude-plugin/marketplace.json`` or
    any file under ``plugins/protean/`` drifts from the render, an installer gets
    a stale plugin. Pin the whole tree to the render for the installed version.
    """
    assert plugin_drift(_REPO_ROOT, PACK_VERSION) == []


def test_committed_plugin_version_tracks_the_framework_version() -> None:
    """The committed ``plugin.json`` version equals ``protean.__version__``.

    This is what would red on a release bump without the ``.bumpversion.toml``
    entry that stamps the plugin manifest, so it doubles as the churn guard.
    """
    manifest = json.loads(
        (_REPO_ROOT / PLUGIN_MANIFEST_PATH).read_text(encoding="utf-8")
    )
    assert manifest["version"] == protean.__version__


# --- completeness -----------------------------------------------------------


def test_every_skill_projects_a_skill_md() -> None:
    """Every pack skill has a matching ``SKILL.md`` in the render, and no extra."""
    skills = iter_skills()
    assert len(skills) > 0, "expected the pack to carry skills"

    rendered = render_plugin_files(PACK_VERSION)
    rendered_skill_mds = {
        path
        for path in rendered
        if path.startswith(f"{PLUGIN_SKILLS_ROOT}/") and path.endswith(f"/{SKILL_FILE}")
    }
    expected = {f"{PLUGIN_SKILLS_ROOT}/{name}/{SKILL_FILE}" for name in skills}
    assert rendered_skill_mds == expected


# --- asset fidelity ---------------------------------------------------------


def test_skill_with_assets_and_references_projects_them() -> None:
    """A skill carrying ``assets/`` and ``references/`` has both projected.

    ``projector`` is such a skill. Its asset and reference files must land in the
    render byte for byte.
    """
    rendered = render_plugin_files(PACK_VERSION)
    projector_files = {
        path for path in rendered if path.startswith(f"{PLUGIN_SKILLS_ROOT}/projector/")
    }
    assert f"{PLUGIN_SKILLS_ROOT}/projector/{SKILL_FILE}" in projector_files
    assert any("/assets/" in path for path in projector_files)
    assert any("/references/" in path for path in projector_files)


def test_no_package_marker_is_projected() -> None:
    """The pack's ``__init__.py`` package markers never reach the plugin tree.

    They exist only because the pack ships as package data under ``src/protean``;
    they are not part of a skill.
    """
    rendered = render_plugin_files(PACK_VERSION)
    assert not any(path.endswith("/__init__.py") for path in rendered)


def test_skill_files_are_copied_verbatim() -> None:
    """A projected skill file carries the pack source's exact bytes.

    Copying verbatim (rather than re-encoding text) is what keeps the byte-exact
    drift guard honest across platforms.
    """
    rendered = render_plugin_files(PACK_VERSION)
    source = (pack_files() / SKILLS_DIR / "aggregate" / SKILL_FILE).read_bytes()
    assert rendered[f"{PLUGIN_SKILLS_ROOT}/aggregate/{SKILL_FILE}"] == source


# --- manifest shape ---------------------------------------------------------


def test_marketplace_manifest_shape() -> None:
    manifest = marketplace_manifest()
    assert manifest["name"] == "proteanhq"
    assert manifest["owner"]["name"] == "Protean HQ"
    assert len(manifest["plugins"]) == 1
    plugin = manifest["plugins"][0]
    assert plugin["name"] == PLUGIN_NAME
    assert plugin["source"] == PLUGIN_SOURCE


def test_plugin_manifest_shape() -> None:
    manifest = plugin_manifest("1.2.3")
    assert manifest["name"] == PLUGIN_NAME
    assert manifest["license"] == "Apache-2.0"
    assert manifest["author"]["name"] == "Protean HQ"
    assert manifest["version"] == "1.2.3"


def test_committed_marketplace_names_the_plugin_source() -> None:
    """The committed marketplace manifest points at the committed plugin tree."""
    manifest = json.loads((_REPO_ROOT / MARKETPLACE_PATH).read_text(encoding="utf-8"))
    assert manifest["name"] == "proteanhq"
    assert [p["source"] for p in manifest["plugins"]] == [PLUGIN_SOURCE]


# --- the CLI verb -----------------------------------------------------------


def test_check_passes_on_the_committed_tree() -> None:
    result = runner.invoke(app, ["build-plugin", "--check", "-o", str(_REPO_ROOT)])
    assert result.exit_code == 0, result.output
    assert "up to date" in _flat(result.output)


def test_check_reports_drift_on_a_stale_tree_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """A mutated committed file makes ``--check`` exit 1 without touching disk."""
    write_plugin(tmp_path, PACK_VERSION)
    manifest = tmp_path / PLUGIN_MANIFEST_PATH
    stale = '{\n  "name": "protean",\n  "version": "0.0.0"\n}\n'
    manifest.write_text(stale, encoding="utf-8")

    result = runner.invoke(app, ["build-plugin", "--check", "-o", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "drift" in _flat(result.output).lower()
    # Writes nothing: the mutated file is left exactly as we wrote it.
    assert manifest.read_text(encoding="utf-8") == stale


def test_check_reports_an_extra_file_as_drift(tmp_path: Path) -> None:
    """A file the render no longer produces is reported as ``extra`` drift."""
    write_plugin(tmp_path, PACK_VERSION)
    orphan = tmp_path / PLUGIN_SKILLS_ROOT / "ghost" / SKILL_FILE
    orphan.parent.mkdir(parents=True)
    orphan.write_text("stale skill\n", encoding="utf-8")

    result = runner.invoke(app, ["build-plugin", "--check", "-o", str(tmp_path)])

    assert result.exit_code == 1, result.output
    assert "extra" in _flat(result.output)


def test_build_then_check_round_trips_clean(tmp_path: Path) -> None:
    """Rendering into a fresh dir then checking it there reports no drift."""
    write_result = runner.invoke(app, ["build-plugin", "-o", str(tmp_path)])
    assert write_result.exit_code == 0, write_result.output
    assert (tmp_path / MARKETPLACE_PATH).is_file()

    check_result = runner.invoke(app, ["build-plugin", "--check", "-o", str(tmp_path)])
    assert check_result.exit_code == 0, check_result.output


def test_build_prunes_a_file_the_render_no_longer_produces(tmp_path: Path) -> None:
    """A regenerate clears an orphan skill file left from a previous render."""
    write_plugin(tmp_path, PACK_VERSION)
    orphan = tmp_path / PLUGIN_SKILLS_ROOT / "ghost" / SKILL_FILE
    orphan.parent.mkdir(parents=True)
    orphan.write_text("stale skill\n", encoding="utf-8")

    result = runner.invoke(app, ["build-plugin", "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert not orphan.exists()
    assert not orphan.parent.exists()


def test_drift_reports_a_missing_file(tmp_path: Path) -> None:
    """A rendered file the tree lacks is reported as ``missing`` drift."""
    write_plugin(tmp_path, PACK_VERSION)
    (tmp_path / PLUGIN_MANIFEST_PATH).unlink()

    drift = plugin_drift(tmp_path, PACK_VERSION)

    assert f"missing {PLUGIN_MANIFEST_PATH}" in drift


def test_build_exits_2_when_the_target_cannot_be_written(tmp_path: Path) -> None:
    """A filesystem error while writing surfaces as a clean exit ``2``."""
    # Block the write: put a regular file where the ``.claude-plugin`` directory
    # must be created, so the first mkdir raises.
    (tmp_path / ".claude-plugin").write_text("not a directory", encoding="utf-8")

    result = runner.invoke(app, ["build-plugin", "-o", str(tmp_path)])

    assert result.exit_code == 2, result.output
    assert "could not write" in _flat(result.output)


def test_prune_empty_dirs_is_a_no_op_on_a_missing_root(tmp_path: Path) -> None:
    """Pruning a directory that does not exist does nothing and does not raise."""
    _prune_empty_dirs(tmp_path / PLUGIN_ROOT)  # never created
    assert not (tmp_path / PLUGIN_ROOT).exists()


def test_help_lists_build_plugin() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "build-plugin" in result.output
