"""Every inline TOML block on a docs page parses.

A TOML block is inline when its body is anything other than one ``--8<--``
include line. Each inline block on a page under ``docs/`` must parse with
``tomllib``, unless its first line is ``# fragment``. The included files are
checked by the tests that load them.
"""

from __future__ import annotations

import tomllib

import pytest

from tests.docs.support import DOCS
from tests.support.snippets import extract_toml_blocks

pytestmark = pytest.mark.no_test_domain


def _is_include(source: str) -> bool:
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    return len(lines) == 1 and lines[0].startswith("--8<--")


def toml_parse_problems(text: str) -> list[str]:
    """Return ``line N: error`` for each inline, non-fragment TOML block that does not parse."""
    problems = []
    for block in extract_toml_blocks(text):
        if block.fragment or _is_include(block.source):
            continue
        try:
            tomllib.loads(block.source)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"line {block.line}: {exc}")
    return problems


def test_every_inline_toml_block_on_the_docs_pages_parses():
    pages = sorted(DOCS.rglob("*.md"))
    assert pages, f"no pages under {DOCS}"

    problems = [
        f"{page.relative_to(DOCS).as_posix()}: {problem}"
        for page in pages
        for problem in toml_parse_problems(page.read_text(encoding="utf-8"))
    ]

    assert problems == []


def test_an_inline_block_that_does_not_parse_is_reported():
    source = (
        "```toml\n"
        "[databases.default]\n"
        'provider = "memory"\n'
        "\n"
        "[databases.default]\n"
        'provider = "sqlite"\n'
        "```\n"
    )

    [problem] = toml_parse_problems(source)
    assert problem.startswith("line 2: ")


def test_a_fragment_an_include_and_a_valid_block_are_accepted():
    source = (
        '```toml\n# fragment\n...\nidentity_strategy = "uuid"\n```\n'
        '```toml\n--8<-- "guides/x/domain.toml"\n```\n'
        '    ```toml\n    --8<-- "guides/x/nested.toml"\n    ```\n'
        '```toml\n[databases.default]\nprovider = "memory"\n```\n'
    )

    assert toml_parse_problems(source) == []
