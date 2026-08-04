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

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _collected() -> tuple[int, int]:
    """(collected, deselected) from a real collection run."""
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--ignore=tests/support",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout
    m = re.search(r"(\d+)/(\d+) tests collected \((\d+) deselected\)", out)
    if not m:
        m2 = re.search(r"(\d+) tests collected", out)
        return (int(m2.group(1)), 0) if m2 else (0, 0)
    return int(m.group(1)), int(m.group(3))


def _count(pattern: str, root: Path) -> int:
    return sum(
        len(re.findall(pattern, p.read_text(encoding="utf-8", errors="ignore"), re.M))
        for p in root.rglob("*.py")
    )


def _lines(root: Path) -> int:
    return sum(
        len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        for p in root.rglob("*.py")
    )


def main() -> None:
    tests_dir, src_dir = REPO / "tests", REPO / "src" / "protean"
    collected, deselected = _collected()
    functions = _count(r"^\s*(?:async )?def test_", tests_dir)
    classes = _count(r"^\s*class Test", tests_dir)
    fixtures = _count(r"^\s*@pytest\.fixture", tests_dir)
    parametrized = _count(r"^\s*@pytest\.mark\.parametrize", tests_dir)
    src_lines, test_lines = _lines(src_dir), _lines(tests_dir)

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
    if deselected:
        print(
            f"\n  ({deselected} deselected by marker; `tests/support` excluded — "
            f"fixtures, not tests)"
        )
    print(
        "\nOther pages quote a round figure and link here. "
        "tests/test_metrics_are_single_sourced.py enforces that."
    )


if __name__ == "__main__":
    main()
