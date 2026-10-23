"""The published changelog page must match `CHANGELOG.md`.

`docs/changelog.md` and `docs/changelog.xml` are generated from `CHANGELOG.md`
by `scripts/build_changelog_page.py` and committed, the same way the `llms.txt`
snapshot and the canonical IR baseline are. Committing the output keeps the page
readable in the repo and on GitHub, and makes a stale page a test failure rather
than something a reader notices after it ships.

Editing `CHANGELOG.md` without regenerating is the whole failure mode here, so
that is what these tests catch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from build_changelog_page import (
    FEED,
    OLDEST_SHOWN,
    PAGE,
    SOURCE,
    build,
    parse,
    shown,
    sort_key,
)

REGENERATE = "Run: uv run python scripts/build_changelog_page.py"


@pytest.fixture(scope="module")
def rendered() -> tuple[str, str, int]:
    return build()


def test_page_matches_changelog(rendered: tuple[str, str, int]) -> None:
    page, _, _ = rendered
    assert PAGE.read_text() == page, (
        f"{PAGE.relative_to(REPO)} is out of step with CHANGELOG.md. {REGENERATE}"
    )


def test_feed_matches_changelog(rendered: tuple[str, str, int]) -> None:
    _, feed, _ = rendered
    assert FEED.read_text() == feed, (
        f"{FEED.relative_to(REPO)} is out of step with CHANGELOG.md. {REGENERATE}"
    )


def test_every_shown_release_reaches_the_page(rendered: tuple[str, str, int]) -> None:
    """A release newer than the cutoff is on the page, with its own anchor."""
    page, _, _ = rendered
    for release in shown(parse(SOURCE.read_text())):
        assert f"#{release.anchor}" in page, (
            f"{release.version} is newer than {OLDEST_SHOWN} but has no anchor "
            "on the page."
        )


def test_versions_are_the_only_headings(rendered: tuple[str, str, int]) -> None:
    """The right-rail table of contents is the version picker.

    It only works as one while nothing else on the page is an `h2`, so group
    names are rendered as styled paragraphs rather than headings.
    """
    page, _, _ = rendered
    headings = [line for line in page.split("\n") if line.startswith(("## ", "### "))]
    assert all(line.startswith("## ") for line in headings), headings

    versions = {release.version for release in shown(parse(SOURCE.read_text()))}
    for line in headings:
        assert line.split()[1] in versions, f"{line} is not a release heading"


def test_no_link_is_left_relative_to_the_repo_root() -> None:
    """`CHANGELOG.md` links in-repo files from the root; the page is in `docs/`.

    An unrewritten `docs/...` link resolves one level too deep and 404s. The
    strict build does not catch it, because it only validates links to local
    files and these can be absolute URLs.
    """
    assert "](docs/" not in PAGE.read_text()


def test_release_candidate_sorts_below_its_release() -> None:
    assert sort_key("0.15.0rc1") < sort_key("0.15.0")
    assert sort_key("0.16.0") > sort_key("0.15.0")
    assert sort_key("0.17.1") > sort_key("0.17.0")


def test_older_releases_stay_off_the_page(rendered: tuple[str, str, int]) -> None:
    """The record stays whole in `CHANGELOG.md`; the page carries the recent part."""
    page, _, _ = rendered
    cutoff = sort_key(OLDEST_SHOWN)
    older = [
        release.version
        for release in parse(SOURCE.read_text())
        if release.date and sort_key(release.version) < cutoff
    ]
    assert older, "nothing is older than the cutoff, so this test proves nothing"
    for version in older:
        assert f"## {version} " not in page, f"{version} is older than {OLDEST_SHOWN}"
