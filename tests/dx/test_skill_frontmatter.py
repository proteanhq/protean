"""Parse every DX-pack skill's frontmatter and hold it to Claude Code's rules.

Claude Code reads a skill's YAML frontmatter to decide when the skill fires. If
the YAML does not parse, Claude Code drops every field and lists the skill as
"Skill from protean plugin", so the skill never triggers. A description longer
than 1,024 characters is past Claude Code's hard limit. This test parses the
frontmatter of every ``skills/*/SKILL.md`` and requires a mapping whose
``name`` equals the skill's folder name and whose description is at most 1,024
characters.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the frontmatter test reads skills by path",
        allow_module_level=True,
    )

DESCRIPTION_LIMIT = 1024


def _frontmatter(text: str) -> str | None:
    """Return the YAML between the leading ``---`` lines, or None if absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index])
    return None


def frontmatter_problems(skills_root: Path) -> list[str]:
    """Check every ``*/SKILL.md`` under ``skills_root`` and list the problems.

    Each problem names the file relative to ``skills_root``.
    """
    problems = []
    for path in sorted(skills_root.glob("*/SKILL.md")):
        label = path.relative_to(skills_root).as_posix()
        block = _frontmatter(path.read_text(encoding="utf-8"))
        if block is None:
            problems.append(f"{label}: no frontmatter block between '---' lines")
            continue
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as exc:
            problems.append(f"{label}: frontmatter is not valid YAML: {exc}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{label}: frontmatter is not a mapping")
            continue
        folder = path.parent.name
        if data.get("name") != folder:
            problems.append(
                f"{label}: name {data.get('name')!r} differs from folder {folder!r}"
            )
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(f"{label}: description is missing or empty")
        elif len(description) > DESCRIPTION_LIMIT:
            problems.append(
                f"{label}: description is {len(description)} characters, "
                f"over the {DESCRIPTION_LIMIT}-character limit"
            )
    return problems


def test_skill_discovery_is_not_vacuous():
    skills = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    independent = [
        d for d in SKILLS_ROOT.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()
    ]
    assert skills, "discovered no SKILL.md files under the DX pack"
    assert len(skills) == len(independent)
    assert len(skills) >= 35


def test_every_skill_frontmatter_is_valid():
    problems = frontmatter_problems(SKILLS_ROOT)
    assert problems == [], "skill frontmatter problems:\n" + "\n".join(problems)


# --- Negative tests on synthetic skill folders -------------------------------


def _write_skill(root: Path, folder: str, frontmatter: str) -> None:
    skill_dir = root / folder
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n# Body\n", encoding="utf-8"
    )


def test_a_valid_skill_has_no_problems(tmp_path):
    _write_skill(tmp_path, "good", 'name: good\ndescription: "Use when: anything"')
    assert frontmatter_problems(tmp_path) == []


def test_invalid_yaml_fails_and_names_the_file(tmp_path):
    _write_skill(
        tmp_path, "broken", "name: broken\ndescription: Supports three flavors: a, b"
    )
    problems = frontmatter_problems(tmp_path)
    assert len(problems) == 1
    assert problems[0].startswith("broken/SKILL.md: frontmatter is not valid YAML")


def test_name_differing_from_folder_fails(tmp_path):
    _write_skill(tmp_path, "folder", "name: other\ndescription: Something")
    assert frontmatter_problems(tmp_path) == [
        "folder/SKILL.md: name 'other' differs from folder 'folder'"
    ]


def test_over_long_description_fails(tmp_path):
    _write_skill(tmp_path, "long", "name: long\ndescription: " + "x" * 1025)
    assert frontmatter_problems(tmp_path) == [
        "long/SKILL.md: description is 1025 characters, over the 1024-character limit"
    ]


def test_description_at_the_limit_passes(tmp_path):
    _write_skill(tmp_path, "edge", "name: edge\ndescription: " + "x" * 1024)
    assert frontmatter_problems(tmp_path) == []


def test_missing_frontmatter_fails(tmp_path):
    (tmp_path / "bare").mkdir()
    # The body has a `---` rule and a closing `---`, but the file does not
    # start with one, so there is no frontmatter block.
    (tmp_path / "bare" / "SKILL.md").write_text(
        "# No frontmatter\n\nname: bare\n\n---\n\nText.\n\n---\n"
    )
    assert frontmatter_problems(tmp_path) == [
        "bare/SKILL.md: no frontmatter block between '---' lines"
    ]


def test_non_mapping_frontmatter_fails(tmp_path):
    _write_skill(tmp_path, "listy", "- name\n- description")
    assert frontmatter_problems(tmp_path) == [
        "listy/SKILL.md: frontmatter is not a mapping"
    ]


def test_missing_description_fails(tmp_path):
    _write_skill(tmp_path, "nodesc", "name: nodesc")
    assert frontmatter_problems(tmp_path) == [
        "nodesc/SKILL.md: description is missing or empty"
    ]
