#!/usr/bin/env python3
"""Recompute the numbers on `docs/community/quality.md`.

That page declares itself the single source of truth for Protean's test metrics,
and every other surface is supposed to quote a round figure and link to it. This
script is the other half of that promise: one command to refresh the one page,
so the numbers are cheap to keep honest.

    uv run python scripts/metrics.py

Prints the figures; it does not edit the page, because the surrounding prose
usually needs a human sentence when a number moves a lot.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Markers for tests that run against a real database, broker or event store.
# A test carrying any of them counts as an integration test; the rest are core.
BACKING_MARKERS = {
    "database": "Database (generic)",
    "redis": "Redis",
    "eventstore": "Event Store",
    "elasticsearch": "Elasticsearch",
    "postgresql": "PostgreSQL",
    "sqlite": "SQLite",
    "mysql": "MySQL",
    "message_db": "MessageDB",
    "mssql": "MSSQL",
}


class _Tally:
    """Collects the selected tests and their markers in one collection run."""

    def __init__(self) -> None:
        self.collected = 0
        self.deselected = 0
        self.integration = 0
        self.by_marker: Counter[str] = Counter()

    def pytest_deselected(self, items) -> None:
        self.deselected += len(items)

    def pytest_collection_finish(self, session) -> None:
        self.collected = len(session.items)
        for item in session.items:
            names = {m.name for m in item.iter_markers()} & BACKING_MARKERS.keys()
            self.by_marker.update(names)
            self.integration += bool(names)


def _collect() -> _Tally:
    tally = _Tally()
    os.chdir(REPO)
    # Collection prints every test id; only the tally is wanted.
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = pytest.main(
            ["--collect-only", "-q", "--ignore=tests/support"], plugins=[tally]
        )
    # A module that fails to import still leaves the other items collected, so
    # the tally would look plausible while missing whole files.
    if status != pytest.ExitCode.OK:
        sys.stderr.write(output.getvalue())
        sys.exit(f"Test collection failed ({status!r}); no metrics printed.")
    return tally


def _count(pattern: str, root: Path) -> int:
    return sum(
        len(
            re.findall(
                pattern, p.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE
            )
        )
        for p in root.rglob("*.py")
    )


def _lines(root: Path) -> int:
    return sum(
        len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        for p in root.rglob("*.py")
    )


def main() -> None:
    tests_dir, src_dir = REPO / "tests", REPO / "src" / "protean"
    tally = _collect()
    collected = tally.collected
    functions = _count(r"^\s*(?:async )?def test_", tests_dir)
    classes = _count(r"^\s*class Test", tests_dir)
    fixtures = _count(r"^\s*@pytest\.fixture", tests_dir)
    parametrized = _count(r"^\s*@pytest\.mark\.parametrize", tests_dir)
    src_lines, test_lines = _lines(src_dir), _lines(tests_dir)
    core = collected - tally.integration

    print("Paste these into docs/community/quality.md:\n")
    print(f"  Total Tests        {collected:,}")
    print(f"  Test Functions     {functions:,}")
    print(f"  Test Classes       {classes:,}")
    print(f"  Pytest Fixtures    {fixtures:,}")
    print(f"  Parametrized Tests {parametrized:,}")
    print(
        f"  Test-to-Code Ratio {test_lines / src_lines:.1f}:1"
        f"  ({test_lines:,} test lines / {src_lines:,} src lines)"
    )
    print("\n  Core vs. Integration")
    print(f"    Core tests         {core:,}  {core / collected:.0%}")
    print(
        f"    Integration tests  {tally.integration:,}"
        f"  {tally.integration / collected:.0%}"
    )
    print("\n  Infrastructure Coverage (marked tests)")
    for marker, count in tally.by_marker.most_common():
        print(f"    {BACKING_MARKERS[marker]:<20}{count:,}")
    if tally.deselected:
        print(
            f"\n  ({tally.deselected} deselected by marker; `tests/support` excluded as "
            f"fixtures, not tests)"
        )
    print(
        "\nOther pages quote a round figure and link here. "
        "tests/test_metrics_are_single_sourced.py enforces that."
    )


if __name__ == "__main__":
    main()
