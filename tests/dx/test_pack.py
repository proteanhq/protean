"""Tests for the DX pack accessor (``protean.dx``).

These read the pack from the source tree. The clean-venv wheel check in CI
proves the same resources survive the build into an installed wheel.
"""

from pathlib import Path

import pytest

import protean
from protean import dx
from protean.dx import pack

# These tests read package data; they never touch a Domain, so skip the autouse
# test_domain fixture and its initialization cost.
pytestmark = pytest.mark.no_test_domain

# The pack ships as package data; on a filesystem install its root is a real
# directory, which the layers guards below walk to check each skill's structure.
PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR
RULES_DIR = "rules"

# The seed skill carries prose only: no runnable examples and no references
# layer. Every other skill is a teaching skill that ships both. Naming the seed
# here keeps the layers guards free of a hard-coded skill list, so they still
# hold after a re-sync adds or prunes teaching skills.
SEED_SKILL = "protean-overview"


def _license_is_apache(skill_md_text: str) -> bool:
    """Return whether a SKILL.md declares the framework's Apache-2.0 license.

    The contract is two-sided: the Apache-2.0 declaration is present and the
    word ``Proprietary`` (the license the skills carried in their private source
    repo) appears nowhere. A skill that drops the declaration or keeps the old
    proprietary marker fails.
    """
    return "license: Apache-2.0" in skill_md_text and "Proprietary" not in skill_md_text


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
    # Exercise the filter and the sort deterministically, independent of the
    # real pack's contents. Point the accessor at a fake pack root with two
    # skills (created out of alphabetical order), a stray file, and a stray
    # directory with no SKILL.md; only the two skills count, and they come back
    # sorted.
    skills_root = tmp_path / pack.SKILLS_DIR
    for name in ("beta", "alpha"):
        (skills_root / name).mkdir(parents=True)
        (skills_root / name / pack.SKILL_FILE).write_text("# skill", encoding="utf-8")
    (skills_root / "README.md").write_text("not a skill", encoding="utf-8")
    (skills_root / "__pycache__").mkdir()  # a directory, but no SKILL.md

    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.iter_skills() == ["alpha", "beta"]


# --- The full pack: completeness, license, and the two reference layers -------


def test_iter_skills_returns_the_full_teaching_pack():
    # The pack ships the seed plus the full teaching set, not the placeholder
    # alone. Assert the accessor lists every skill directory on disk and that
    # the set is far larger than the seed, so a pack that regressed to the
    # placeholder (or lost most skills) fails here.
    skills = dx.iter_skills()
    on_disk = sorted(
        child.name
        for child in SKILLS_ROOT.iterdir()
        if child.is_dir() and (child / dx.SKILL_FILE).is_file()
    )

    assert skills == on_disk
    assert SEED_SKILL in skills
    assert len(skills) >= 36
    # Spot-check well-known teaching skills so a pack missing the real corpus,
    # yet somehow still large, cannot pass.
    for expected in ("aggregate", "event", "command-handler", "repository"):
        assert expected in skills, f"{expected} missing from the pack"


@pytest.mark.parametrize("skill", dx.iter_skills())
def test_every_skill_declares_the_apache_license(skill):
    text = dx.read_pack_text(dx.SKILLS_DIR, skill, dx.SKILL_FILE)

    assert _license_is_apache(text), (
        f"{skill}/SKILL.md must declare license: Apache-2.0 and carry no "
        f"Proprietary marker"
    )


def test_license_check_rejects_non_apache_frontmatter():
    # Prove the license guard is not vacuous: a Proprietary marker and a missing
    # declaration both fail it.
    assert _license_is_apache("---\nname: x\nlicense: Apache-2.0\n---\n")
    assert not _license_is_apache("---\nname: x\nlicense: Proprietary\n---\n")
    assert not _license_is_apache("---\nname: x\n---\n# no license line\n")


def test_every_teaching_skill_ships_a_references_layer():
    # A re-sync must not silently drop a skill's references/ layer. Every skill
    # that ships runnable examples (an assets/ dir) must also ship its deep-docs
    # references/ dir with at least one readable page. The seed carries neither.
    teaching_skills = [
        child.name
        for child in SKILLS_ROOT.iterdir()
        if child.is_dir() and (child / "assets").is_dir()
    ]
    assert teaching_skills, "no teaching skills with an assets/ dir found"
    assert SEED_SKILL not in teaching_skills

    for skill in teaching_skills:
        references = SKILLS_ROOT / skill / "references"
        assert references.is_dir(), f"{skill} ships no references/ layer"
        pages = sorted(references.glob("*.md"))
        assert pages, f"{skill}/references is empty"
        # Reachable through the accessor, the same read path the wheel uses.
        assert dx.read_pack_text(dx.SKILLS_DIR, skill, "references", pages[0].name)


def test_rules_layer_ships_the_cross_cutting_pattern_files():
    # The top-level rules/ layer must survive a re-sync too. Assert it ships the
    # cross-cutting pattern files and that a known one is readable through the
    # accessor.
    rules_dir = PACK_ROOT / RULES_DIR
    assert rules_dir.is_dir(), "the pack ships no rules/ layer"
    rule_files = sorted(rules_dir.glob("*.md"))
    assert len(rule_files) >= 12

    assert dx.read_pack_text(RULES_DIR, "protean-conventions.md")
