"""A markdown table cell may not contain an unescaped `|`.

GitHub Flavored Markdown splits table rows on `|` before inline parsing, so a
pipe inside a code span still ends the cell unless it is escaped. The row then
renders with the wrong number of columns and the text after the pipe is lost.

The repo already writes `int \\| None` everywhere this comes up, 32 rows of it,
so this is an established convention rather than a new rule. It is a convention
nothing enforced: a `TTL = "${CACHE_TTL|3600}"` example went into a table cell
unescaped and rendered fine under mkdocs, which is more forgiving, while being
broken on github.com where the same file is browsed.

This checks the GitHub-breaking half only. The escaped form has a problem of its
own, tracked separately: python-markdown renders the backslash literally inside
a code span, so those 32 rows publish as `str \\| None` on the docs site. The
construct is unwinnable in a table cell and the real fix is to keep pipes out of
one, which is why the cache TTL example moved to a fenced block below its table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

pytestmark = pytest.mark.no_test_domain


def _offending_rows(text: str) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        # `\|` is the escaped form and is fine; a bare `|` is not.
        bad.extend(
            (number, span)
            for span in re.findall(r"`([^`]+)`", line)
            if re.search(r"(?<!\\)\|", span)
        )
    return bad


class TestTableCellsEscapeTheirPipes:
    def test_the_docs_tree_is_there(self):
        assert DOCS.is_dir(), f"{DOCS} is missing"
        assert list(DOCS.rglob("*.md")), "no markdown found under docs/"

    def test_no_table_cell_has_an_unescaped_pipe(self):
        offenders = []
        for page in sorted(DOCS.rglob("*.md")):
            for number, span in _offending_rows(page.read_text(encoding="utf-8")):
                offenders.append(f"{page.relative_to(DOCS)}:{number} -> `{span}`")

        assert not offenders, (
            "A `|` inside a table cell ends the cell on GitHub even within a code "
            "span, so the row renders short and the rest of the text disappears. "
            "Escape it as `\\|`, or move the example out of the table:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_check_recognises_both_forms(self):
        """Guard the guard: it must accept `\\|` and reject a bare `|`."""
        assert _offending_rows(r"| `a` | `int \| None` | fine |") == []
        assert _offending_rows("| `a` | `int | None` | broken |")
