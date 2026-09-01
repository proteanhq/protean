"""Tests for the DX pack accessor (``protean.dx``).

These read the pack from the source tree. The clean-venv wheel check in CI
proves the same resources survive the build into an installed wheel.
"""

import pytest

import protean
from protean import dx
from protean.dx import pack

# These tests read package data; they never touch a Domain, so skip the autouse
# test_domain fixture and its initialization cost.
pytestmark = pytest.mark.no_test_domain


def test_pack_version_is_the_framework_version():
    # The pack ships inside the wheel, so its version is the framework version.
    assert protean.__version__ == dx.PACK_VERSION
    assert dx.PACK_VERSION


def test_pack_files_returns_the_pack_root():
    root = dx.pack_files()

    assert (root / dx.AGENTS_SOURCE).is_file()
    assert (root / dx.SKILLS_DIR).is_dir()


def test_load_agents_source_returns_seed_content():
    text = dx.load_agents_source()

    assert "Protean agent instructions" in text
    assert "dx-pack-seed" in text


def test_read_pack_text_reads_a_nested_resource():
    text = dx.read_pack_text(dx.SKILLS_DIR, "protean-overview", dx.SKILL_FILE)

    assert "name: protean-overview" in text


@pytest.mark.parametrize("bad", ["..", ".", "", "a/b", "a\\b"])
def test_read_pack_text_rejects_path_traversal(bad):
    # A caller must not be able to escape the pack with `..` or a separator.
    with pytest.raises(ValueError):
        dx.read_pack_text(dx.SKILLS_DIR, bad)


def test_iter_skills_lists_the_seed_skill():
    skills = dx.iter_skills()

    assert len(skills) > 0, "Expected at least the seed skill in the DX pack"
    assert "protean-overview" in skills


def test_iter_skills_lists_skill_dirs_only_and_sorts(tmp_path, monkeypatch):
    # The seed pack has a single valid skill, so it cannot exercise the filter
    # or the sort. Point the accessor at a fake pack root with two skills
    # (created out of alphabetical order), a stray file, and a stray directory
    # with no SKILL.md; only the two skills count, and they come back sorted.
    skills_root = tmp_path / pack.SKILLS_DIR
    for name in ("beta", "alpha"):
        (skills_root / name).mkdir(parents=True)
        (skills_root / name / pack.SKILL_FILE).write_text("# skill", encoding="utf-8")
    (skills_root / "README.md").write_text("not a skill", encoding="utf-8")
    (skills_root / "__pycache__").mkdir()  # a directory, but no SKILL.md

    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.iter_skills() == ["alpha", "beta"]
