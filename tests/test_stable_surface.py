"""The stable-surface page is normative, so it must match the shipped code.

`docs/reference/stable-surface.md` enumerates every public export and assigns it
a compatibility tier. A page like that is worse than useless once it drifts: it
would promise stability for a name that no longer exists, or stay silent about
one that does. These tests fail the build when the page and `__all__` disagree,
so a new export cannot ship without being classified.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import protean
import protean.exceptions
import protean.fields

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
PAGE = DOCS / "reference" / "stable-surface.md"

TIERS = {"Stable", "Provisional", "Internal"}

# Module name as written in the page -> the module whose __all__ it must match.
MODULES = {
    "protean": protean,
    "protean.fields": protean.fields,
    "protean.exceptions": protean.exceptions,
}

_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*(\w+)\s*\|$")


def _index() -> dict[tuple[str, str], str]:
    """Parse the export index into {(module, export): tier}."""
    text = PAGE.read_text(encoding="utf-8")
    try:
        body = text.split("<!-- surface-index:start -->", 1)[1].split(
            "<!-- surface-index:end -->", 1
        )[0]
    except IndexError:  # pragma: no cover - guarded by its own test below
        pytest.fail(
            "stable-surface.md is missing the surface-index:start/end markers "
            "that delimit the normative export table."
        )

    entries: dict[tuple[str, str], str] = {}
    for line in body.splitlines():
        match = _ROW.match(line.strip())
        if match:
            export, module, tier = match.groups()
            entries[(module, export)] = tier
    return entries


@pytest.fixture(scope="module")
def index() -> dict[tuple[str, str], str]:
    return _index()


class TestExportIndexIsParseable:
    def test_page_exists(self):
        assert PAGE.is_file(), f"{PAGE} is missing"

    def test_index_has_entries(self, index):
        # Guards against a formatting change silently reducing every
        # comparison below to an empty-set-equals-empty-set tautology.
        assert len(index) > 50


class TestIndexMatchesShippedExports:
    @pytest.mark.parametrize("module_name", sorted(MODULES))
    def test_index_matches_dunder_all(self, index, module_name):
        """Every exported name is classified, and nothing extra is listed."""
        documented = {export for module, export in index if module == module_name}
        shipped = set(MODULES[module_name].__all__)

        assert shipped, f"{module_name}.__all__ is unexpectedly empty"

        missing = shipped - documented
        assert not missing, (
            f"{module_name} exports {sorted(missing)} but stable-surface.md does "
            "not classify them. Add a row to the export index with the tier."
        )

        extra = documented - shipped
        assert not extra, (
            f"stable-surface.md lists {sorted(extra)} for {module_name}, but they "
            "are not in its __all__. Remove the rows or restore the exports."
        )

    def test_every_tier_is_recognised(self, index):
        unknown = {tier for tier in index.values() if tier not in TIERS}
        assert not unknown, f"Unknown tier(s) in the export index: {sorted(unknown)}"

    def test_top_level_exports_are_all_stable(self, index):
        """`protean.__all__` is the headline surface: it is Stable by definition."""
        not_stable = {
            export
            for (module, export), tier in index.items()
            if module == "protean" and tier != "Stable"
        }
        assert not not_stable, (
            f"Top-level exports {sorted(not_stable)} are classified below Stable. "
            "Either promote them or stop exporting them from `protean`."
        )


# The compatibility promise, stated once. Every page that quotes it must quote
# it exactly: a contract that is paraphrased differently in three places is a
# contract nobody can cite.
CONTRACT = "Code that runs warning-free on 1.N runs unmodified on 1.N+1."

CONTRACT_PAGES = (
    PAGE,
    DOCS / "reference" / "versioning-policy.md",
    REPO / "README.md",
    DOCS / "adr" / "0004-release-workflow-and-breaking-change-policy.md",
)


class TestPageStatesTheContract:
    @pytest.mark.parametrize("path", CONTRACT_PAGES, ids=lambda p: p.name)
    def test_contract_sentence_appears_verbatim(self, path):
        """Every page stating the contract must state the same sentence."""
        assert path.is_file(), f"{path} is missing"
        normalised = " ".join(path.read_text(encoding="utf-8").split())
        assert CONTRACT in normalised, (
            f"{path.name} does not contain the contract sentence verbatim. "
            f"Expected: {CONTRACT!r}"
        )

    def test_all_three_tiers_are_defined(self):
        text = PAGE.read_text(encoding="utf-8")
        for tier in TIERS:
            assert f"**{tier}.**" in text, f"Tier {tier} has no definition section"
