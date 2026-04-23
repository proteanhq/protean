"""Guard the logging documentation against silent bit-rot.

A future refactor that renames or moves any of the three logging pages
would leave the mkdocs nav, the ``how-do-i`` index, and every in-docs
cross-reference pointing at files that no longer exist. These tests fail
fast on that class of drift by asserting the canonical filenames,
top-level sections, and markdown cross-links remain intact.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"

GUIDE_PATH = DOCS / "guides" / "server" / "logging.md"
REFERENCE_PATH = DOCS / "reference" / "logging.md"
CONCEPT_PATH = DOCS / "concepts" / "observability" / "logging.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected docs file at {path}"
    content = path.read_text(encoding="utf-8")
    assert content.strip(), f"docs file {path} is empty"
    return content


def _h1(text: str) -> str | None:
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _assert_all_present(content: str, sections: list[str], label: str) -> None:
    assert sections, f"{label} required_sections list must not be empty"
    for section in sections:
        assert section in content, f"missing section {section!r} in {label}"


def test_logging_guide_page_exists() -> None:
    content = _read(GUIDE_PATH)
    assert _h1(content) == "Logging"


def test_logging_reference_page_exists() -> None:
    content = _read(REFERENCE_PATH)
    assert _h1(content) == "Logging"

    # The reference enumerates every framework logger. If one of these
    # sections disappears the docs no longer match the code and operators
    # lose the catalog they rely on for queries.
    required_sections = [
        "## `[logging]` config section",
        "### `protean.access`",
        "### `protean.perf`",
        "### `protean.security`",
        "### `protean.server.engine`",
        "### `protean.server.subscription`",
        "### `protean.server.outbox_processor`",
        "### `protean.core.unit_of_work`",
        "### `protean.adapters.broker.redis`",
        "### `protean.adapters.repository.sqlalchemy`",
        "## Trace-context fields",
        "## Correlation fields",
        "## Redaction",
        "## Multi-worker logging",
    ]
    _assert_all_present(content, required_sections, "reference")


def test_logging_concept_page_exists() -> None:
    content = _read(CONCEPT_PATH)
    assert _h1(content) == "Logging"

    # These headings anchor links from the guide and reference; if they
    # rename without a corresponding link update, cross-references rot
    # silently.
    required_sections = [
        "## Why structured logs?",
        "## The wide event pattern",
        "## How Protean builds wide events automatically",
        "## Query-oriented field design",
        "## High-cardinality fields and backend choice",
        "## Why redaction is processor-based",
        "## Multi-worker hygiene",
        "## What Protean deliberately does not do",
    ]
    _assert_all_present(content, required_sections, "concept page")


def test_mkdocs_nav_includes_logging_pages() -> None:
    nav = _read(MKDOCS_YML)
    # Match the exact nav entries so both the presence and the canonical
    # relative path are pinned.
    assert "guides/server/logging.md" in nav
    assert "reference/logging.md" in nav
    assert "concepts/observability/logging.md" in nav


@pytest.mark.parametrize(
    "page",
    [GUIDE_PATH, REFERENCE_PATH, CONCEPT_PATH],
    ids=["guide", "reference", "concept"],
)
def test_pages_cross_link(page: Path) -> None:
    """Each of the three pages must link to the other two so readers can
    navigate between quadrants without bouncing off the sidebar."""
    content = _read(page)

    others = {
        GUIDE_PATH: ("reference/logging.md", "concepts/observability/logging.md"),
        REFERENCE_PATH: (
            "guides/server/logging.md",
            "concepts/observability/logging.md",
        ),
        CONCEPT_PATH: ("guides/server/logging.md", "reference/logging.md"),
    }[page]

    assert others, "cross-link targets must not be empty"
    for target in others:
        # Match the full relative path, not just the basename: all three
        # pages share the filename ``logging.md``, so a basename-only check
        # would accept a page that links to itself twice.
        link_pattern = re.compile(rf"\]\([^)]*{re.escape(target)}[^)]*\)")
        assert link_pattern.search(content), (
            f"page {page.name} has no markdown link to {target}"
        )
