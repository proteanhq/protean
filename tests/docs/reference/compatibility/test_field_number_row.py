"""Check the ``field_number_changed`` row of docs/reference/compatibility/index.md.

The row names the change type ``classify_changes()`` emits and links to the
guide section on landing a deliberate breaking change. The test fails when the
change type or the guide heading is renamed without the page.
"""

import re

from protean.ir.diff import _AVRO_CHANGE_SAFETY
from tests.docs.support import DOCS

PAGE = DOCS / "reference/compatibility/index.md"
GUIDE = DOCS / "guides/compatibility-checking.md"
ANCHOR = "landing-a-deliberate-breaking-change"


def _row() -> str:
    rows = [
        line
        for line in PAGE.read_text(encoding="utf-8").splitlines()
        if line.startswith("|") and "**Breaking** (`field_number_changed`)" in line
    ]
    assert len(rows) == 1
    return rows[0]


def test_the_row_names_a_change_type_the_checker_emits():
    _row()
    assert "field_number_changed" in _AVRO_CHANGE_SAFETY


def test_the_row_links_to_a_guide_heading_that_exists():
    assert f"compatibility-checking.md#{ANCHOR}" in _row()
    headings = [
        re.sub(r"[^a-z0-9 -]", "", line.lstrip("#").strip().lower()).replace(" ", "-")
        for line in GUIDE.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert ANCHOR in headings
