"""Only one page may state an exact test count.

`docs/community/quality.md` says it is "the single source of truth for these
numbers; other pages quote round figures and link here". The policy was written
down and never enforced, so the count appeared on seven surfaces carrying six
different values — 7,674 in one badge, 10,386 in another, 10,640 in the source
of truth, and 10,000+ in two prose claims, while the suite had passed 12,000.

The counts cannot be pinned (every PR adds tests), so this does not assert a
number. It asserts there is only **one place to change**, which is what makes
the refresh cheap enough to actually happen: `uv run python scripts/metrics.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE_OF_TRUTH = REPO / "docs" / "community" / "quality.md"

# A precise count of tests: four-or-more digits, comma-grouped or not, near the
# word "test". Round figures like "12,000+" are the approved form elsewhere and
# are deliberately not matched.
_EXACT_COUNT = re.compile(
    r"(?<![\d.])(\d{1,3},\d{3}|\d{4,})(?!\+)(?![\d.])(?=[^\n]{0,40}?\btest)"
    r"|\btests?\b[^\n]{0,40}?(?<![\d.])(\d{1,3},\d{3}|\d{4,})(?!\+)(?![\d.])",
    re.I,
)

_SEARCHED = ["README.md", "docs/index.md", "docs/why-protean.md"]

pytestmark = pytest.mark.no_test_domain


def _exact_counts(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        if "quality.md" in line or "/community/quality" in line:
            continue  # a link to the source of truth is the approved form
        hits.extend(
            next(g for g in match.groups() if g)
            for match in _EXACT_COUNT.finditer(line)
        )
    return hits


class TestOnlyQualityMdCarriesExactCounts:
    def test_the_source_of_truth_exists_and_says_so(self):
        assert SOURCE_OF_TRUTH.is_file(), f"{SOURCE_OF_TRUTH} is missing"
        text = SOURCE_OF_TRUTH.read_text(encoding="utf-8")
        assert "single source of truth" in text, (
            "quality.md no longer claims to be the single source of truth; "
            "either restore the claim or retire this guard"
        )

    @pytest.mark.parametrize("relative", _SEARCHED)
    def test_no_other_page_states_an_exact_test_count(self, relative):
        page = REPO / relative
        if not page.is_file():
            pytest.skip(f"{relative} not present")

        found = _exact_counts(page.read_text(encoding="utf-8"))
        assert not found, (
            f"{relative} states an exact test count ({found}). Only "
            "docs/community/quality.md may. Quote a round figure such as "
            "'12,000+' and link to the quality report instead, so there is one "
            "place to refresh when the number moves."
        )

    def test_the_guard_can_tell_the_two_forms_apart(self):
        """Exact counts are rejected; round figures and links are not."""
        assert _exact_counts("The suite has 12,440 tests.")
        assert _exact_counts("| Tests | 7,674 |")
        assert not _exact_counts("Over 12,000+ tests back every release.")
        assert not _exact_counts("See the [quality report](community/quality.md).")
