"""A declared break must reach the migration guide.

The 0.17.0 release audit found 23 behaviour changes documented nowhere a user
would look. The most diagnostic case was the `/readyz` response-shape change: it
was correctly identified as breaking and correctly written up in its changelog
fragment, and still never reached the migration guide, because that handoff was
manual and nothing checked it.

These tests make the handoff a build failure instead of a habit. A fragment that
declares a break must name the migration section that tells a user what to do,
and that section must actually exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FRAGMENTS = REPO / "changes"
MIGRATION_DIR = REPO / "docs" / "reference" / "migration"

VALID_CATEGORIES = {
    "added",
    "changed",
    "deprecated",
    "removed",
    "fixed",
    "security",
}

# A fragment *declares* a break with one of these, not by mentioning the word in
# passing ("breaking `set_ttl` into two methods" is prose, not a declaration).
_DECLARES_BREAK = re.compile(
    r"^\*\*Breaking\b|\*\*Breaking-change classification", re.M
)
_MIGRATION_LINK = re.compile(r"\*\*Migration:\*\*\s*\[[^\]]+\]\(([^)]+)\)")


def _fragments() -> list[Path]:
    return sorted(
        p
        for p in FRAGMENTS.glob("*.md")
        if p.name != "README.md" and not p.name.startswith(".")
    )


def _anchors(text: str) -> set[str]:
    """GitHub-style anchors for every heading in a markdown document."""
    anchors = set()
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        anchors.add(re.sub(r"\s+", "-", slug).strip("-"))
    return anchors


@pytest.fixture(scope="module")
def fragments() -> list[Path]:
    found = _fragments()
    assert found, "no changelog fragments found; the glob or path is wrong"
    return found


class TestFragmentNaming:
    def test_every_fragment_is_named_for_an_issue_and_category(self, fragments):
        """`<issue>.<category>.md`, per changes/README.md."""
        bad = []
        for p in fragments:
            parts = p.name.split(".")
            if len(parts) != 3:
                bad.append(p.name)
                continue
            stem, category, _ = parts
            # A slug is allowed for a change with no issue (the Apache-2.0
            # relicense landed direct to main); everything else names its issue.
            if not (stem.isdigit() or re.fullmatch(r"[a-z][a-z0-9-]*", stem)):
                bad.append(p.name)
            elif category not in VALID_CATEGORIES:
                bad.append(f"{p.name} (unknown category {category!r})")
        assert not bad, (
            f"Fragments must be named <issue>.<category>.md with a category from "
            f"{sorted(VALID_CATEGORIES)}: {bad}"
        )


class TestDeclaredBreaksReachTheMigrationGuide:
    """The rule that would have caught the `/readyz` miss."""

    def test_every_declared_break_links_to_a_migration_section(self, fragments):
        missing = [
            p.name
            for p in fragments
            if _DECLARES_BREAK.search(p.read_text(encoding="utf-8"))
            and not _MIGRATION_LINK.search(p.read_text(encoding="utf-8"))
        ]
        assert not missing, (
            "These fragments declare a breaking change but do not point at the "
            "migration section that tells a user what to do. Add a line:\n"
            "    **Migration:** [Section title](https://docs.proteanhq.com/"
            "reference/migration/v0-NN/#section-anchor)\n"
            f"Missing: {missing}"
        )

    def test_every_migration_link_resolves_to_a_real_section(self, fragments):
        """A pointer at a section that does not exist is worse than none."""
        guides = {
            p.name: _anchors(p.read_text(encoding="utf-8"))
            for p in MIGRATION_DIR.glob("v0-*.md")
        }
        assert guides, "no migration guides found"

        broken = []
        for p in fragments:
            match = _MIGRATION_LINK.search(p.read_text(encoding="utf-8"))
            if not match:
                continue
            url = match.group(1)
            if "#" not in url:
                broken.append(f"{p.name}: link has no anchor")
                continue
            path_part, anchor = url.rsplit("#", 1)
            version = re.search(r"v0-\d+", path_part.replace("/", "-"))
            if not version:
                broken.append(f"{p.name}: cannot tell which guide {url!r} means")
                continue
            guide = f"{version.group(0)}.md"
            if guide not in guides:
                broken.append(f"{p.name}: no such guide {guide}")
            elif anchor not in guides[guide]:
                broken.append(f"{p.name}: {guide} has no section #{anchor}")

        assert not broken, (
            "Migration links must resolve to a real heading in the guide they "
            f"name: {broken}"
        )


class TestTheAuditedBreaksAreCovered:
    """Pin the specific changes the 0.17.0 audit found undocumented.

    Named individually because each was missed once already, and a generic
    "the guide is long enough" assertion would not have caught any of them.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def guide(cls) -> str:
        return (MIGRATION_DIR / "v0-17.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "topic",
        [
            "sanitiz",  # length bounds checked after sanitization
            "retention_maxlen",  # trimming on by default, can drop unread
            "circuit_breaker_threshold",  # breaker on by default
            "checks.subscriptions",  # /readyz response shape
            "ExpectedVersionError",  # OCC now actually conflicts
            "ObjectNotFoundError",  # update() on a non-persisted entity
            "gap_timeout_seconds",  # $all subscriptions wait at gaps
            "target_broker",  # outbox NOT NULL
            "elasticsearch_dsl",  # dependency floor drop
        ],
    )
    def test_guide_covers(self, guide, topic):
        assert topic in guide, (
            f"The 0.17 migration guide does not mention {topic!r}, which the "
            "release audit identified as a behaviour change users must act on."
        )
