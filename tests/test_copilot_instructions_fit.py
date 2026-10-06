"""Copilot review instruction files must fit in what Copilot code review reads.

Copilot code review reads only the first 4,000 characters of each custom
instruction file and ignores the rest without warning. The repository-wide file
had grown past that, so its last sections never reached a review. Rules that
apply to part of the tree belong in a path-scoped file under
`.github/instructions/`, which gets its own 4,000 characters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.no_test_domain

GITHUB_DIR = Path(__file__).resolve().parents[1] / ".github"
COPILOT_REVIEW_CHAR_LIMIT = 4000

PATH_SCOPED_FILES = sorted((GITHUB_DIR / "instructions").glob("*.instructions.md"))
INSTRUCTION_FILES = [GITHUB_DIR / "copilot-instructions.md", *PATH_SCOPED_FILES]


@pytest.mark.parametrize(
    "path", INSTRUCTION_FILES, ids=lambda p: str(p.relative_to(GITHUB_DIR))
)
def test_instruction_file_fits_in_copilot_review_limit(path: Path) -> None:
    size = len(path.read_text(encoding="utf-8"))
    assert size <= COPILOT_REVIEW_CHAR_LIMIT, (
        f"{path.relative_to(GITHUB_DIR.parent)} is {size} characters. Copilot "
        f"code review reads only the first {COPILOT_REVIEW_CHAR_LIMIT}. Move "
        "path-specific rules into .github/instructions/<name>.instructions.md "
        "with an applyTo glob."
    )


def test_path_scoped_instruction_files_declare_apply_to() -> None:
    for path in PATH_SCOPED_FILES:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n") and "\napplyTo:" in text.split("\n---", 1)[0], (
            f"{path.name} has no applyTo frontmatter, so Copilot applies it nowhere."
        )
