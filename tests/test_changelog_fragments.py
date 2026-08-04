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
    """Every anchor mkdocs will publish for the headings in a document.

    Repeated headings are the reason this counts rather than collecting a set of
    slugs. The guides use one "Who is affected" per change, four of them in
    v0-16 alone, and mkdocs disambiguates by appending `_1`, `_2` and so on
    (python-markdown's `toc`, an underscore; GitHub's own renderer uses a hyphen,
    which is not the scheme the published links resolve against). Collapsing
    them would reject `#who-is-affected_3` as a broken link when it is the only
    way to reach the fourth section.
    """
    anchors: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug).strip("-")
        candidate, repeat = slug, 0
        while candidate in anchors:
            repeat += 1
            candidate = f"{slug}_{repeat}"
        anchors.add(candidate)
    return anchors


@pytest.fixture(scope="module")
def fragments() -> list[Path]:
    found = _fragments()
    assert found, "no changelog fragments found; the glob or path is wrong"
    return found


@pytest.fixture(scope="module")
def guide() -> str:
    return (MIGRATION_DIR / "v0-17.md").read_text(encoding="utf-8")


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


class TestAnchorsMatchWhatMkdocsPublishes:
    """The link checker is only as good as its model of mkdocs' anchors."""

    def test_repeated_headings_get_the_underscore_suffix(self):
        anchors = _anchors(
            "## Who is affected\n## Who is affected\n## Who is affected\n"
        )
        assert anchors == {
            "who-is-affected",
            "who-is-affected_1",
            "who-is-affected_2",
        }

    def test_underscores_in_a_heading_survive(self):
        """`retention_maxlen` is a config key, and the slug keeps the underscore."""
        assert "retention_maxlen-trims-streams" in _anchors(
            "## retention_maxlen trims streams\n"
        )

    def test_every_guides_repeated_headings_are_reachable(self):
        """v0-16 has four "Who is affected" sections; all four need an anchor."""
        guide = (MIGRATION_DIR / "v0-16.md").read_text(encoding="utf-8")
        headings = [line for line in guide.splitlines() if line.startswith("#")]
        assert len(_anchors(guide)) == len(headings), (
            "one anchor per heading; a collapsed duplicate makes a real section "
            "unlinkable and the link test would reject a valid link to it"
        )
