"""The docs must name the right exception for a missing `@apply` handler.

An event-sourced aggregate raises `IncorrectUsageError` ("No @apply handler
registered for event ...") when it raises or replays an event that has no
`@apply` handler. Several pages once said `NotImplementedError` instead. The
behavior itself is covered in
`tests/event_sourced_aggregates/test_raise_apply_integration.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

pytestmark = pytest.mark.no_test_domain

_APPLY = re.compile(r"@apply|apply handler", re.IGNORECASE)

# A sentence can wrap, so look at the lines just before the exception name too.
_LOOKBACK = 3


def _wrong_claims(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        if "NotImplementedError" not in line:
            continue
        window = lines[max(0, index - _LOOKBACK) : index + 1]
        if any(_APPLY.search(candidate) for candidate in window):
            found.append((index + 1, line.strip()))
    return found


def test_guard_flags_a_wrapped_claim():
    text = "Every event needs an `@apply`\nhandler, or it raises `NotImplementedError`."
    assert _wrong_claims(text) == [(2, "handler, or it raises `NotImplementedError`.")]


def test_guard_ignores_unrelated_not_implemented_error():
    text = "The adapter raises `NotImplementedError` for `F`-bearing predicates."
    assert _wrong_claims(text) == []


def test_no_page_claims_not_implemented_error_for_a_missing_apply_handler():
    pages = sorted(DOCS.rglob("*.md"))
    assert pages, f"no markdown pages found under {DOCS}"

    offenders = [
        f"{page.relative_to(DOCS)}:{line_no}: {line}"
        for page in pages
        for line_no, line in _wrong_claims(page.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "A missing @apply handler raises IncorrectUsageError, "
        "not NotImplementedError:\n" + "\n".join(offenders)
    )
