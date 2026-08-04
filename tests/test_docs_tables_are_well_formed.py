"""A markdown table cell may not contain a `|` in a code span.

GitHub Flavored Markdown splits table rows on `|` before inline parsing, so a
pipe inside a code span still ends the cell. Escaping it as `\\|` satisfies
GitHub and breaks the docs site instead: python-markdown does not strip the
backslash inside a code span, so 32 rows published as `str \\| None`.

There is no spelling of a pipe inside a backtick span that is right in both.
The form that works uses a raw `<code>` tag with the HTML entity:

    | `a` | <code>str &#124; None</code> |

GFM resolves entities *after* splitting rows, so the cell survives, and a
browser draws the entity as a pipe. Verified against a real `mkdocs build`:
zero backslashes leaked, and every converted span shows a real pipe.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

pytestmark = pytest.mark.no_test_domain


def _offending_rows(text: str) -> list[tuple[int, str]]:
    """Code spans inside a table row that contain a pipe, escaped or not."""
    bad: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        # Both spellings. `<code>` is the form this repo now recommends, and a
        # literal pipe inside one breaks the row exactly as it does inside
        # backticks: checked against GitHub's own renderer, a three-column row
        # carrying `<code>int | None</code>` comes back with two cells and the
        # third silently dropped. Non-greedy on purpose, so a row holding two
        # code tags is not read as one span running across both.
        spans = re.findall(r"`([^`]+)`", line) + re.findall(r"<code>(.*?)</code>", line)
        bad.extend((number, span) for span in spans if "|" in span)
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

    def test_the_check_recognises_every_broken_form(self):
        """Guard the guard: only the entity inside a code tag is acceptable."""
        assert _offending_rows("| `a` | `int | None` | bare backticks |")
        assert _offending_rows(r"| `a` | `int \| None` | escaped backticks |")
        # The recommended form is only right when the pipe is an entity: a
        # literal one inside `<code>` breaks the row just the same, and went
        # unchecked while this file recommended the tag.
        assert _offending_rows("| `a` | <code>int | None</code> | bare tag |")

        assert _offending_rows("| `a` | <code>int &#124; None</code> | ok |") == []

    def test_two_code_tags_in_one_row_are_not_read_as_one_span(self):
        """The Q-operator table has two, and a greedy match would span both."""
        row = "| <code>&#124;</code> | OR | <code>Q(a) &#124; Q(b)</code> |"
        assert _offending_rows(row) == []
