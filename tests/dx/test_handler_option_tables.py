"""The handler skills' option tables match the options each handler accepts.

``@domain.command_handler`` and ``@domain.event_handler`` reject an option the
handler class does not list in ``_default_options``. The command-handler and
event-handler skills each carry a table of those options with their defaults.
These tests read each table and compare it with the class, so a new option or a
changed default fails here until the table catches up. The projector skill's
table and the handler tables in ``docs/`` are checked for the same option names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.projector import BaseProjector
from protean.utils.container import DerivedDefault

pytestmark = pytest.mark.no_test_domain

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR
DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"

if not SKILLS_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the tables are read by path",
        allow_module_level=True,
    )

# ``stream_category`` has no fixed default: it comes from the aggregate named
# in ``part_of``, so the table describes it in words. The words stand in only
# for a class default that is ``None`` or a ``DerivedDefault``. A concrete
# default must appear in the table as its value.
DERIVED = {"stream_category": "derived from part_of"}


def option_table(text: str) -> dict[str, str]:
    """Return ``{option: default cell}`` from the page's one ``Option`` table.

    The table needs a ``Default`` column. Bold markers and backticks around a
    cell are removed.
    A page with more than one such table, or a table that lists an option
    twice, fails: either would let a wrong row hide behind a right one.
    """
    lines = text.splitlines()
    tables = []
    for index, line in enumerate(lines):
        cells = _cells(line)
        if not cells or cells[0] != "Option" or "Default" not in cells:
            continue
        default_column = cells.index("Default")
        rows: dict[str, str] = {}
        for row in lines[index + 2 :]:
            if not row.strip().startswith("|"):
                break
            row_cells = _cells(row)
            if row_cells[0] in rows:
                raise AssertionError(f"option {row_cells[0]} is listed twice")
            rows[row_cells[0]] = row_cells[default_column]
        tables.append(rows)
    if not tables:
        raise AssertionError("no table with an Option and a Default column")
    if len(tables) > 1:
        raise AssertionError(f"{len(tables)} tables with an Option column, expected 1")
    return tables[0]


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [
        cell.strip().strip("*").strip("`") for cell in stripped.strip("|").split("|")
    ]


def render_default(name: str, value: Any) -> str:
    """The text a table's Default cell holds for ``value``."""
    if name in DERIVED and (value is None or isinstance(value, DerivedDefault)):
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


def _section(text: str, heading: str) -> str:
    """The text under ``heading`` up to the next heading of the same level."""
    start = text.index(heading + "\n")
    level = heading.split(" ", 1)[0]
    rest = text[start + len(heading) + 1 :]
    end = rest.find("\n" + level + " ")
    return rest if end == -1 else rest[:end]


# The docs tables write some defaults in words ("—", "*required*", "from
# aggregate"), so they are checked for the option names only.
DOCS_TABLES = [
    (
        "reference/domain-elements/element-decorators.md",
        "### `Domain.command_handler`",
        BaseCommandHandler,
    ),
    (
        "reference/domain-elements/element-decorators.md",
        "### `Domain.event_handler`",
        BaseEventHandler,
    ),
    ("guides/change-state/command-handlers.md", None, BaseCommandHandler),
    (
        "reference/domain-elements/element-decorators.md",
        "### `Domain.projector`",
        BaseProjector,
    ),
]


@pytest.mark.parametrize("page, heading, handler_cls", DOCS_TABLES)
def test_docs_option_table_lists_the_handler_options(page, heading, handler_cls):
    text = (DOCS_ROOT / page).read_text(encoding="utf-8")
    if heading is not None:
        text = _section(text, heading)

    assert set(option_table(text)) == {name for name, _ in handler_cls._default_options}


def test_projector_skill_lists_the_projector_options():
    # This table has Purpose and Required columns in place of Default, so only
    # the option names are compared.
    text = (SKILLS_ROOT / "projector" / "SKILL.md").read_text(encoding="utf-8")
    lines = _section(text, "## Projector options").splitlines()
    names = [cells[0] for cells in map(_cells, lines) if cells][2:]

    assert names, "projector option table has no rows"
    assert set(names) == {name for name, _ in BaseProjector._default_options}


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


def test_a_page_with_two_option_tables_fails():
    with pytest.raises(AssertionError, match="2 tables"):
        option_table(TABLE + TABLE)


def test_a_table_listing_an_option_twice_fails():
    doubled = TABLE.replace(
        "| `suppress_checks` | `()` | Codes to skip |",
        "| `suppress_checks` | `[]` | Codes to skip |\n"
        "| `suppress_checks` | `()` | Codes to skip |",
    )

    with pytest.raises(AssertionError, match="suppress_checks is listed twice"):
        option_table(doubled)


def test_a_concrete_stream_category_default_is_not_exempt():
    options = [
        ("part_of", None),
        ("stream_category", "orders"),
        ("suppress_checks", ()),
    ]

    assert table_problems(option_table(TABLE), options) == [
        "stream_category: Default is 'derived from part_of', the class has \"'orders'\""
    ]


def test_a_derived_stream_category_default_is_exempt():
    options = [
        ("part_of", None),
        ("stream_category", DerivedDefault(lambda cls: None)),
        ("suppress_checks", ()),
    ]

    assert table_problems(option_table(TABLE), options) == []
