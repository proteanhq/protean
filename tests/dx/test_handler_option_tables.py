"""The handler skills' option tables match the options each handler accepts.

``@domain.command_handler`` and ``@domain.event_handler`` reject an option the
handler class does not list in ``_default_options``. The command-handler and
event-handler skills each carry a table of those options with their defaults.
These tests read each table and compare it with the class, so a new option or a
changed default fails here until the table catches up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler

pytestmark = pytest.mark.no_test_domain

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR

if not SKILLS_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the tables are read by path",
        allow_module_level=True,
    )

# ``stream_category`` has no fixed default: it comes from the aggregate named
# in ``part_of``, so the table describes it in words.
DERIVED = {"stream_category": "derived from part_of"}


def option_table(text: str) -> dict[str, str]:
    """Return ``{option: default cell}`` from the first table headed ``Option``.

    The table needs a ``Default`` column. Backticks around a cell are removed.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        cells = _cells(line)
        if not cells or cells[0] != "Option" or "Default" not in cells:
            continue
        default_column = cells.index("Default")
        rows = {}
        for row in lines[index + 2 :]:
            if not row.strip().startswith("|"):
                break
            row_cells = _cells(row)
            rows[row_cells[0]] = row_cells[default_column]
        return rows
    raise AssertionError("no table with an Option and a Default column")


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]


def render_default(name: str, value: Any) -> str:
    """The text a table's Default cell holds for ``value``."""
    if name in DERIVED:
        return DERIVED[name]
    return repr(value)


def table_problems(
    table: dict[str, str], default_options: list[tuple[str, Any]]
) -> list[str]:
    """Every way ``table`` differs from ``default_options``."""
    expected = {name: render_default(name, value) for name, value in default_options}
    problems = [f"missing option {name}" for name in expected if name not in table]
    problems += [f"unknown option {name}" for name in table if name not in expected]
    problems += [
        f"{name}: Default is {table[name]!r}, the class has {cell!r}"
        for name, cell in expected.items()
        if name in table and table[name] != cell
    ]
    return problems


@pytest.mark.parametrize(
    "skill, handler_cls",
    [
        ("command-handler", BaseCommandHandler),
        ("event-handler", BaseEventHandler),
    ],
)
def test_option_table_matches_the_handler_class(skill, handler_cls):
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    table = option_table(text)

    assert table, f"{skill} option table has no rows"
    assert table_problems(table, handler_cls._default_options) == []


def test_command_and_event_handler_options_differ_where_documented():
    command_options = {name for name, _ in BaseCommandHandler._default_options}
    event_options = {name for name, _ in BaseEventHandler._default_options}

    assert command_options - event_options == {"timeout"}
    assert event_options - command_options == {"source_stream"}


# --- The comparison fails on a table that drifts ----------------------------

OPTIONS = [("part_of", None), ("stream_category", None), ("suppress_checks", ())]

TABLE = """
Some text.

| Option | Default | Description |
|--------|---------|-------------|
| `part_of` | `None` | The aggregate |
| `stream_category` | derived from part_of | The stream |
| `suppress_checks` | `()` | Codes to skip |

After the table.
"""


def test_a_matching_table_has_no_problems():
    assert option_table(TABLE) == {
        "part_of": "None",
        "stream_category": "derived from part_of",
        "suppress_checks": "()",
    }
    assert table_problems(option_table(TABLE), OPTIONS) == []


def test_a_table_missing_an_option_fails():
    table = option_table(
        TABLE.replace("| `suppress_checks` | `()` | Codes to skip |", "")
    )

    assert table_problems(table, OPTIONS) == ["missing option suppress_checks"]


def test_a_table_with_an_extra_option_fails():
    table = option_table(TABLE) | {"timeout": "None"}

    assert table_problems(table, OPTIONS) == ["unknown option timeout"]


def test_a_table_with_a_wrong_default_fails():
    table = option_table(TABLE) | {"suppress_checks": "[]"}

    assert table_problems(table, OPTIONS) == [
        "suppress_checks: Default is '[]', the class has '()'"
    ]


def test_a_page_without_an_option_table_fails():
    with pytest.raises(AssertionError, match="no table"):
        option_table("| Name | Value |\n|---|---|\n| a | b |\n")
