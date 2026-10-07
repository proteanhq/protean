"""No page teaches an event handler that listens on another aggregate's stream.

An event handler that is ``part_of`` one aggregate and sets ``stream_category``
to another aggregate's stream is what ``check`` reports as
``EVENT_HANDLER_FOREIGN_EVENT``. The pages below teach the other shape: the
handler stays with the aggregate that owns the event and issues a command.

A code block on these pages may still show ``stream_category`` on an event
handler in two cases:

- a ``$any`` handler, which reacts to every event on a stream on purpose;
- the anti-pattern itself, when the block or the text just before it names
  ``EVENT_HANDLER_FOREIGN_EVENT``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
REPO_ROOT = Path(__file__).resolve().parents[2]

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the pages are read by path",
        allow_module_level=True,
    )

SKILLS = ("event-handler", "add-event", "add-use-case", "refactor-introduce-events")
GUIDE = REPO_ROOT / "docs" / "guides" / "consume-state" / "event-handlers.md"

FENCE = re.compile(r"^([ \t]*)```[^\n]*\n(.*?)^\1```", re.MULTILINE | re.DOTALL)
EVENT_HANDLER = re.compile(r"event_handler\((.*?)\)\s*\n", re.DOTALL)
CODE = "EVENT_HANDLER_FOREIGN_EVENT"
# How much text before a block may carry its anti-pattern label.
LABEL_WINDOW = 400


def _pages() -> list[Path]:
    pages = [
        page
        for skill in SKILLS
        for page in sorted((PACK_ROOT / dx.SKILLS_DIR / skill).rglob("*.md"))
    ]
    pages += sorted((PACK_ROOT / "rules").glob("*.md"))
    if GUIDE.is_file():
        pages.append(GUIDE)
    return pages


def _unlabelled_foreign_handlers(text: str) -> list[int]:
    """Line numbers of code blocks that show the foreign handler unlabelled."""
    lines = []
    for block in FENCE.finditer(text):
        code = block.group(2)
        before = text[max(0, block.start() - LABEL_WINDOW) : block.start()]
        if CODE in code or CODE in before or '"$any"' in code:
            continue
        if any(
            "stream_category" in handler.group(1)
            for handler in EVENT_HANDLER.finditer(code)
        ):
            lines.append(text.count("\n", 0, block.start()) + 1)
    return lines


def test_no_page_shows_an_unlabelled_foreign_handler() -> None:
    pages = _pages()
    assert pages, "the pack must ship the pages this test reads"

    found = {
        str(page): lines
        for page in pages
        if (lines := _unlabelled_foreign_handlers(page.read_text()))
    }
    assert found == {}


def test_the_scan_finds_an_unlabelled_foreign_handler() -> None:
    page = (
        "Sync the stock:\n\n"
        "```python\n"
        "@domain.event_handler(\n"
        "    part_of=Inventory, stream_category=Order.meta_.stream_category\n"
        ")\n"
        "class OrderEventsHandler:\n"
        "    @handle(OrderShipped)\n"
        "    def on_shipped(self, event): ...\n"
        "```\n"
    )
    assert _unlabelled_foreign_handlers(page) == [3]


def test_the_scan_accepts_a_labelled_anti_pattern_and_an_any_handler() -> None:
    page = (
        f"Wrong: `check` reports this as `{CODE}`.\n\n"
        "```python\n"
        "@domain.event_handler(part_of=Inventory, stream_category='order')\n"
        "class OrderEventsHandler: ...\n"
        "```\n\n"
        "```python\n"
        "@domain.event_handler(part_of=AuditLog, stream_category='task')\n"
        "class TaskAuditor:\n"
        '    @handle("$any")\n'
        "    def on_any(self, event): ...\n"
        "```\n"
    )
    assert _unlabelled_foreign_handlers(page) == []
