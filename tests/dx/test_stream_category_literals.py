"""No skill or docs page writes a bare stream category in ``stream_categories``.

A projector's stream category is qualified by the domain name
(``<domain>::user``). A projector subscribed to a bare ``"user"`` initializes
cleanly, raises nothing and never receives an event, so neither the snippet
runner nor a domain ``check`` notices it. The pages derive the category from
the aggregate (``aggregates=[User]`` or ``User.meta_.stream_category``) or write
it in full. This guard reads every ``stream_categories=[...]`` list in the pack
and in ``docs/`` and fails on a string literal without ``::``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = Path(str(dx.pack_files()))
DOCS_ROOT = REPO_ROOT / "docs"

_LIST = re.compile(r"stream_categories\s*=\s*\[(.*?)\]", re.DOTALL)
_STRING = re.compile(r"""["']([^"'\n]*)["']""")


def bare_categories(text: str) -> list[tuple[int, str]]:
    """Return ``(line, literal)`` for each bare literal in a ``stream_categories`` list."""
    found = []
    for match in _LIST.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        found.extend(
            (line, literal)
            for literal in _STRING.findall(match.group(1))
            if "::" not in literal
        )
    return found


def test_a_bare_literal_is_reported_and_a_qualified_or_derived_one_is_not():
    text = (
        '@domain.projector(stream_categories=["shop::user"])\n'
        "@domain.projector(\n"
        "    stream_categories=[\n"
        "        User.meta_.stream_category,\n"
        '        "transaction",\n'
        "    ],\n"
        ")\n"
    )
    assert bare_categories(text) == [(3, "transaction")]


def _pages() -> list[Path]:
    roots = [DOCS_ROOT]
    if PACK_ROOT.is_dir():
        roots.append(PACK_ROOT)
    return sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.suffix in {".md", ".py"}
    )


def test_no_page_writes_a_bare_stream_category():
    pages = _pages()
    assert len(pages) > 100

    offenders = [
        f"{path}:{line}: {literal!r}"
        for path in pages
        for line, literal in bare_categories(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
