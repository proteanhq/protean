#!/usr/bin/env python3
"""Render `CHANGELOG.md` into the docs page at `docs/changelog.md`.

`CHANGELOG.md` is the record and stays the file people edit. The docs page is a
second rendering of it, laid out so a reader can find the release they are
upgrading to: each release puts its version beside its changes, and the version
headings are the only `h2` on the page, so the right-rail table of contents
works as a version picker.

    uv run python scripts/build_changelog_page.py

Writes the page and prints what it rendered. `--check` instead compares the
committed page against a fresh render and exits non-zero when they differ, which
is what `tests/test_changelog_page_is_current.py` runs.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "CHANGELOG.md"
PAGE = REPO / "docs" / "changelog.md"
FEED = REPO / "docs" / "changelog.xml"

SITE = "https://docs.proteanhq.com"
REPO_FILE = "https://github.com/proteanhq/protean/blob/main/CHANGELOG.md"

# The page carries the releases people still upgrade from. The file on GitHub
# stays the complete record.
OLDEST_SHOWN = "0.15.0"

# A group with more text than this collapses behind a summary carrying its
# entry count, because an uncollapsed page runs past 20 screens. The budget is
# characters rather than entries: 0.16.0's nine Changed entries are longer than
# 0.17.0's eighteen, so counting entries collapses the wrong ones.
COLLAPSE_OVER_CHARS = 2000
NEVER_COLLAPSE = {"upgrade notes"}

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

_RELEASE = re.compile(r"^## \[([^\]]+)\](?: - (\d{4})-(\d{2})-(\d{2}))?\s*$")
_GROUP = re.compile(r"^### (.+?)\s*$")
_ENTRY = re.compile(r"^- ")

HEADER = f"""# Changelog

Every release of Protean, newest first. This page is generated from
[`CHANGELOG.md`]({REPO_FILE}) in the repository.

Run `protean --version` to check your installed version.

[:material-rss: Subscribe to the feed](changelog.xml)

<div class="pt-changelog" markdown="1">
"""

FOOTER = f"""</div>

Releases before {OLDEST_SHOWN} are in [`CHANGELOG.md`]({REPO_FILE}) in the
repository.
"""


class Release:
    def __init__(self, version: str, date: tuple[str, str, str] | None) -> None:
        self.version = version
        self.date = date
        self.groups: list[tuple[str, list[str]]] = []

    @property
    def anchor(self) -> str:
        return "v" + self.version.replace(".", "-")

    @property
    def pretty_date(self) -> str | None:
        if not self.date:
            return None
        year, month, day = self.date
        return f"{MONTHS[int(month) - 1]} {int(day)}, {year}"

    @property
    def is_empty(self) -> bool:
        return not any(body for _, body in self.groups)


def sort_key(version: str) -> tuple[list[int], int]:
    """Order versions numerically, with a release candidate below its release."""
    head, _, tail = version.partition("rc")
    return ([int(part) for part in head.split(".")], 0 if tail else 1)


def parse(text: str) -> list[Release]:
    releases: list[Release] = []
    current: Release | None = None
    group: list[str] | None = None

    for raw in text.split("\n"):
        line = raw.rstrip()

        release = _RELEASE.match(line)
        if release:
            version, year, month, day = release.groups()
            current = Release(version, (year, month, day) if year else None)
            releases.append(current)
            group = None
            continue

        if current is None:
            continue  # the preamble above the first release

        heading = _GROUP.match(line)
        if heading:
            name = heading.group(1)
            # 0.15.0 declares Added and Fixed twice each. On a page that reads
            # as the same label repeating, so the entries join the first block
            # of that name instead.
            existing = next((b for n, b in current.groups if n == name), None)
            if existing is not None:
                group = existing
            else:
                group = []
                current.groups.append((name, group))
            continue

        if group is not None:
            group.append(line)

    return releases


def rewrite_links(line: str) -> str:
    """`CHANGELOG.md` links are written from the repo root, the page is not.

    An in-repo link reads `docs/guides/x.md` at the repo root. Served from
    inside `docs/`, that prefix points one level too deep.
    """
    return line.replace("](docs/", "](")


def count_entries(body: list[str]) -> int:
    return sum(1 for line in body if _ENTRY.match(line))


def render_group(name: str, body: list[str]) -> str:
    content = "\n".join(rewrite_links(line) for line in body).strip("\n")
    if not content:
        return ""

    label = f'<p class="pt-changelog-group">{name}</p>'
    entries = count_entries(body)
    if name.lower() in NEVER_COLLAPSE or len(content) <= COLLAPSE_OVER_CHARS:
        return f"{label}\n\n{content}\n"

    return (
        f"{label}\n\n"
        f'<details class="pt-changelog-fold" markdown="1">\n'
        f"<summary>{entries} changes</summary>\n\n"
        f"{content}\n\n"
        f"</details>\n"
    )


def render_release(release: Release) -> str:
    meta = [f"## {release.version} {{ #{release.anchor} }}"]
    if release.pretty_date:
        meta.append(f'<p class="pt-changelog-date">{release.pretty_date}</p>')

    body = "\n".join(
        rendered
        for rendered in (render_group(name, lines) for name, lines in release.groups)
        if rendered
    )

    return (
        '<div class="pt-changelog-release" markdown="1">\n'
        '<div class="pt-changelog-meta" markdown="1">\n'
        + "\n".join(meta)
        + "\n</div>\n"
        '<div class="pt-changelog-body" markdown="1">\n\n' + body + "\n</div>\n</div>\n"
    )


def shown(releases: list[Release]) -> list[Release]:
    cutoff = sort_key(OLDEST_SHOWN)
    return [
        release
        for release in releases
        if not release.is_empty
        # An undated release is `[Unreleased]`, which is shown while it has
        # content rather than compared against the cutoff.
        and (release.date is None or sort_key(release.version) >= cutoff)
    ]


def render_page(releases: list[Release]) -> str:
    return (
        HEADER + "\n" + "\n".join(render_release(r) for r in releases) + "\n" + FOOTER
    )


def render_feed(releases: list[Release]) -> str:
    items = []
    for release in releases:
        if not release.date:
            continue
        year, month, day = release.date
        items.append(
            "    <item>\n"
            f"      <title>Protean {release.version}</title>\n"
            f"      <link>{SITE}/changelog/#{release.anchor}</link>\n"
            f'      <guid isPermaLink="true">{SITE}/changelog/#{release.anchor}</guid>\n'
            f"      <pubDate>{_rfc822(year, month, day)}</pubDate>\n"
            f"      <description>Protean {release.version} was released on "
            f"{release.pretty_date}. Read the entries on the changelog page."
            "</description>\n"
            "    </item>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>Protean releases</title>\n"
        f"    <link>{SITE}/changelog/</link>\n"
        "    <description>Every release of Protean, newest first.</description>\n"
        + "\n".join(items)
        + "\n  </channel>\n</rss>\n"
    )


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _rfc822(year: str, month: str, day: str) -> str:
    stamp = date(int(year), int(month), int(day))
    weekday = _WEEKDAYS[stamp.weekday()]
    return (
        f"{weekday}, {int(day):02d} {MONTHS[int(month) - 1][:3]} {year} 00:00:00 +0000"
    )


def build() -> tuple[str, str, int]:
    releases = shown(parse(SOURCE.read_text()))
    return render_page(releases), render_feed(releases), len(releases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the committed page against a fresh render",
    )
    args = parser.parse_args()

    page, feed, count = build()

    if args.check:
        stale = [
            path.relative_to(REPO)
            for path, fresh in ((PAGE, page), (FEED, feed))
            if not path.exists() or path.read_text() != fresh
        ]
        if stale:
            names = ", ".join(str(path) for path in stale)
            print(
                f"{names} is out of step with CHANGELOG.md. "
                "Run: uv run python scripts/build_changelog_page.py",
                file=sys.stderr,
            )
            return 1
        print(f"{PAGE.relative_to(REPO)} and the feed are current ({count} releases)")
        return 0

    PAGE.write_text(page)
    FEED.write_text(feed)
    print(
        f"Wrote {PAGE.relative_to(REPO)} and {FEED.relative_to(REPO)} ({count} releases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
