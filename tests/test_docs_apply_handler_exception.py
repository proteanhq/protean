"""The docs must name the right exception for a missing `@apply` handler.

An event-sourced aggregate raises `IncorrectUsageError` ("No @apply handler
registered for event ...") when it raises or replays an event that has no
`@apply` handler. Several pages once said `NotImplementedError` instead. The
behavior itself is covered in
`tests/event_sourced_aggregates/test_raise_apply_integration.py`.

The guard reads each page one section at a time (heading to heading, code
fences skipped). In a section that talks about `@apply` handlers, any sentence
or table row that names `NotImplementedError` without also naming
`IncorrectUsageError` is flagged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DX_PACK = ROOT / "src" / "protean" / "dx" / "pack"

pytestmark = pytest.mark.no_test_domain

_APPLY_CUE = re.compile(
    r"@apply|apply handler|_apply_handler"
    r"|\b(?:no|missing|without)\b[^.|]{0,40}\bhandler\b"
    r"|handler is registered",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,6}\s")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`])")

_WRONG = "NotImplementedError"
_RIGHT = "IncorrectUsageError"


def _sections(text: str) -> list[list[tuple[int, str]]]:
    """Split a page into sections of (line number, line), skipping code fences."""
    sections: list[list[tuple[int, str]]] = [[]]
    in_fence = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _HEADING.match(line):
            sections.append([])
        sections[-1].append((line_no, line))
    return sections


def _units(section: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Group a section's lines into table rows and prose paragraphs."""
    units: list[list[tuple[int, str]]] = []
    paragraph: list[tuple[int, str]] = []
    for line_no, line in section:
        stripped = line.strip()
        starts_new = (
            not stripped
            or stripped.startswith("|")
            or _HEADING.match(line)
            or _LIST_ITEM.match(line)
        )
        if starts_new and paragraph:
            units.append(paragraph)
            paragraph = []
        if stripped.startswith("|") or _HEADING.match(line):
            units.append([(line_no, line)])
        elif stripped:
            paragraph.append((line_no, line))
    if paragraph:
        units.append(paragraph)
    return units


def _sentences(unit: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Split a unit into sentences, each tagged with the line it starts on."""
    text = " ".join(line.strip() for _, line in unit)
    starts = []
    offset = 0
    for line_no, line in unit:
        starts.append((offset, line_no))
        offset += len(line.strip()) + 1

    def line_at(position: int) -> int:
        return max(line_no for start, line_no in starts if start <= position)

    sentences = []
    position = 0
    for sentence in _SENTENCE_END.split(text):
        position = text.index(sentence, position)
        wrong_at = sentence.find(_WRONG)
        if wrong_at >= 0:
            sentences.append((line_at(position + wrong_at), sentence))
        position += len(sentence)
    return sentences


def _wrong_claims(text: str) -> list[tuple[int, str]]:
    found = []
    for section in _sections(text):
        if not any(_APPLY_CUE.search(line) for _, line in section):
            continue
        for unit in _units(section):
            for line_no, sentence in _sentences(unit):
                if _RIGHT not in sentence:
                    found.append((line_no, sentence))
    return found


def _pages() -> list[Path]:
    return sorted(DOCS.rglob("*.md")) + sorted(DX_PACK.rglob("*.md"))


# The shape of `docs/concepts/internals/event-sourcing.md` before the fix: the
# handler is named in the heading and a list, and the claim sits lines later.
_INTERNALS_PAGE = """\
### `_apply_handler(event)`

Invokes the registered `@apply` handler(s) for an event **without**
touching `_version`. This is the shared core used by both paths:

- Called by `raise_()` during live operations (version already incremented
  by `raise_()` before the handler runs)
- Called by `_apply()` during replay (version incremented by `_apply()`
  after the handler runs)

Raises `NotImplementedError` if no handler is registered.

### `_apply(event)`
"""


def test_guard_flags_the_internals_page_claim():
    assert _wrong_claims(_INTERNALS_PAGE) == [
        (11, "Raises `NotImplementedError` if no handler is registered.")
    ]


def test_guard_flags_a_wrapped_claim():
    text = "Every event needs an `@apply`\nhandler, or it raises `NotImplementedError`."
    assert _wrong_claims(text) == [
        (
            2,
            "Every event needs an `@apply` handler, or it raises `NotImplementedError`.",
        )
    ]


def test_guard_flags_a_claim_with_apply_named_after_it():
    text = "It raises `NotImplementedError`\nwhen the event has no `@apply` method."
    assert _wrong_claims(text) == [
        (1, "It raises `NotImplementedError` when the event has no `@apply` method.")
    ]


def test_guard_flags_a_missing_handler_wording():
    text = "A missing handler raises `NotImplementedError` during replay."
    assert _wrong_claims(text) == [(1, text)]


def test_guard_flags_a_table_row_without_the_word_apply():
    text = (
        "| Exception | When it occurs |\n"
        "|---|---|\n"
        "| `NotImplementedError` | Event-sourced aggregate raises an event"
        " with no matching handler. |"
    )
    assert [line_no for line_no, _ in _wrong_claims(text)] == [3]


def test_guard_ignores_unrelated_not_implemented_error():
    text = "The adapter raises `NotImplementedError` for `F`-bearing predicates."
    assert _wrong_claims(text) == []


def test_guard_ignores_a_sentence_that_also_names_the_right_exception():
    text = "It raises `IncorrectUsageError`, not `NotImplementedError`, for a missing `@apply` handler."
    assert _wrong_claims(text) == []


def test_guard_ignores_a_wrapped_migration_note_naming_both():
    text = (
        "A missing `@apply` handler now raises `IncorrectUsageError`. In 0.14 it\n"
        "raised `NotImplementedError` in place of `IncorrectUsageError`."
    )
    assert _wrong_claims(text) == []


def test_guard_stops_at_a_heading():
    text = (
        "## Apply handlers\n\nEvery event needs an `@apply` handler.\n\n"
        "## Queries\n\nThe adapter raises `NotImplementedError` for `F` predicates."
    )
    assert _wrong_claims(text) == []


def test_guard_skips_code_fences():
    text = (
        "Every event needs an `@apply` handler.\n\n"
        "```python\nraise NotImplementedError\n```"
    )
    assert _wrong_claims(text) == []


def test_no_page_claims_not_implemented_error_for_a_missing_apply_handler():
    pages = _pages()
    assert any(page.is_relative_to(DOCS) for page in pages), f"no pages in {DOCS}"
    assert any(page.is_relative_to(DX_PACK) for page in pages), f"no pages in {DX_PACK}"

    offenders = [
        f"{page.relative_to(ROOT)}:{line_no}: {sentence}"
        for page in pages
        for line_no, sentence in _wrong_claims(page.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "A missing @apply handler raises IncorrectUsageError, "
        "not NotImplementedError:\n" + "\n".join(offenders)
    )
