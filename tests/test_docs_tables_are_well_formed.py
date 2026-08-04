"""A markdown table cell may not contain a `|` in a backtick code span.

GitHub Flavored Markdown splits table rows on `|` before inline parsing, so a
pipe inside a code span still ends the cell. Escaping it as `\\|` satisfies
GitHub and breaks the docs site instead: python-markdown does not strip the
backslash inside a code span, so 33 rows published as `str \\| None`.

There is no spelling of a pipe inside a backtick span that is right in both.
The form that is uses a raw `<code>` tag with the HTML entity:

    | `a` | <code>str &#124; None</code> |

GFM resolves entities *after* splitting rows, so the cell survives, and a
browser draws the entity as a pipe. Verified against a real `mkdocs build`:
zero backslashes leaked, 40 spans showing a real pipe.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

pytestmark = pytest.mark.no_test_domain


def _offending_rows(text: str) -> list[tuple[int, str]]:
    """Backtick code spans inside a table row that contain a pipe, escaped or not."""
    bad: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        bad.extend(
            (number, span) for span in re.findall(r"`([^`]+)`", line) if "|" in span
        )
    return bad


class TestTableCellsCarryNoPipes:
    def test_the_docs_tree_is_there(self):
        assert DOCS.is_dir(), f"{DOCS} is missing"
        assert list(DOCS.rglob("*.md")), "no markdown found under docs/"

    def test_no_table_cell_has_a_pipe_in_a_code_span(self):
        offenders = []
        for page in sorted(DOCS.rglob("*.md")):
            for number, span in _offending_rows(page.read_text(encoding="utf-8")):
                offenders.append(f"{page.relative_to(DOCS)}:{number} -> `{span}`")

        assert not offenders, (
            "A `|` inside a backtick span in a table cell ends the cell on "
            "GitHub; escaping it as `\\|` publishes the backslash on the docs "
            "site. Use a raw code tag with the entity instead, which is correct "
            "in both:\n"
            "    <code>str &#124; None</code>\n  " + "\n  ".join(offenders)
        )

    def test_the_check_recognises_both_broken_forms(self):
        """Guard the guard: a bare pipe and an escaped one are both rejected."""
        assert _offending_rows("| `a` | `int | None` | bare |")
        assert _offending_rows(r"| `a` | `int \| None` | escaped |")
        # The accepted form carries no backticks at all.
        assert _offending_rows("| `a` | <code>int &#124; None</code> | ok |") == []
