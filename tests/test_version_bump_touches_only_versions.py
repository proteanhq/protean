"""The release bump must not rewrite anything but the version.

`.bumpversion.toml` sets a global `search = "{current_version}"` with
`regex = false`, so for any file that does not override it, *every* occurrence of
the current version string is replaced. That is exactly right for a file whose
only matches are version references, and a trap for one that mentions the same
number for another reason.

It sprang once: `pyproject.toml` pinned `"typer>=0.16.0"`, and cutting 0.17.0
rewrote it to `"typer>=0.17.0"`. A third-party floor ratcheting once per release,
inside the tagged commit, with nothing to notice.

Anchoring the files that need it fixes today. This stops tomorrow: a match that
is a dependency on something other than Protean itself fails here, so the file
gets an anchor before the release rather than after.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.no_test_domain


@pytest.fixture(scope="module")
def bump_config() -> dict:
    path = REPO / ".bumpversion.toml"
    assert path.is_file(), f"{path} is missing"
    return tomllib.loads(path.read_text(encoding="utf-8"))["tool"]["bumpversion"]


def _unanchored_files(config: dict) -> list[dict]:
    """Entries that inherit the global replace-every-match search."""
    return [entry for entry in config.get("files", []) if "search" not in entry]


class TestTheBumpOnlyTouchesVersions:
    def test_the_config_is_shaped_as_expected(self, bump_config):
        assert bump_config.get("current_version"), "no current_version configured"
        assert bump_config.get("files"), "no files configured for the bump"

    def test_every_managed_file_exists(self, bump_config):
        missing = [
            e["filename"]
            for e in bump_config["files"]
            if not (REPO / e["filename"]).is_file()
        ]
        assert not missing, f"the bump would fail on missing files: {missing}"

    def test_an_unanchored_file_has_no_third_party_pin_on_this_version(
        self, bump_config
    ):
        """The check that would have caught `typer>=0.16.0`."""
        version = re.escape(bump_config["current_version"])
        # `name>=VERSION` / `name==VERSION`, where the name is not protean itself.
        dependency = re.compile(
            rf"""(?<!\w)(?!protean\b)([A-Za-z][\w.-]*)\s*(==|>=|~=|<=|>|<)\s*{version}"""
        )

        offenders = []
        for entry in _unanchored_files(bump_config):
            text = (REPO / entry["filename"]).read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                match = dependency.search(line)
                if match:
                    offenders.append(
                        f"{entry['filename']}:{number} pins {match.group(1)!r}"
                    )

        assert not offenders, (
            "These files inherit the unanchored global search, and contain the "
            "current version as a dependency pin on something other than "
            "Protean. The next release bump would rewrite that pin:\n  "
            + "\n  ".join(offenders)
            + "\nGive the file its own `search`/`replace` in .bumpversion.toml."
        )
