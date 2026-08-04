"""The `protean.testing` reference page must list everything the module exports.

The page used an mkdocstrings `members:` allowlist naming three of the twelve
names in `__all__`, so nine public test helpers, including `drain` and
`process_and_wait`, rendered nowhere. An allowlist is the right call here, since
it controls the order and grouping, but it is a second list that has to be kept
in step with the first, and nothing was keeping it.

This is the same shape as `tests/test_stable_surface.py`: a documented surface
that claims to be complete has to be checked against the code, or the claim
decays on the next export.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import protean.testing

# These read a markdown file and static metadata. Nothing here needs a domain,
# so skip the autouse fixture that builds one per test.
pytestmark = pytest.mark.no_test_domain

PAGE = Path(__file__).resolve().parents[1] / "docs" / "api" / "testing.md"


def _documented_members() -> list[str]:
    """Every name listed under a `members:` block on the page."""
    members: list[str] = []
    in_block = False
    for line in PAGE.read_text(encoding="utf-8").splitlines():
        if re.fullmatch(r"\s*members:\s*", line):
            in_block = True
            continue
        if in_block:
            entry = re.fullmatch(r"\s*-\s*(\w+)\s*", line)
            if entry:
                members.append(entry.group(1))
            else:
                in_block = False
    return members


class TestTheTestingPageMatchesTheModule:
    def test_the_page_exists_and_lists_members(self):
        assert PAGE.exists(), f"{PAGE} is missing"
        assert _documented_members(), (
            "no `members:` entries parsed from the page; the parser or the "
            "page format changed"
        )

    def test_every_exported_name_is_documented(self):
        documented = set(_documented_members())
        missing = sorted(set(protean.testing.__all__) - documented)
        assert not missing, (
            "`protean.testing` exports these, but docs/api/testing.md does not "
            f"list them, so they render nowhere: {missing}. Add each to a "
            "`members:` block on the page."
        )

    def test_the_page_documents_nothing_that_is_not_exported(self):
        """A stale entry makes mkdocstrings fail the strict build later."""
        extra = sorted(set(_documented_members()) - set(protean.testing.__all__))
        assert not extra, (
            "docs/api/testing.md lists names `protean.testing` does not export: "
            f"{extra}"
        )
