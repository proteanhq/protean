"""Links from the value-object skill to the "Deciding Between Elements" page.

The page lives at ``docs/concepts/building-blocks/choosing-element-types.md``
and publishes under ``https://docs.proteanhq.com``. The pack ships without the
``docs/`` tree, so a skill must link to the published URL. A relative link into
``docs/`` resolves to nothing once the pack is installed.

``tests/dx/test_plugin.py`` only checks that the render matches the pack, so a
dead link in the pack keeps it green. This test checks the links themselves.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from protean import dx
from protean.dx.pack import REFERENCES_DIR as REFERENCES_DIRNAME

# These tests read package data; they never touch a Domain, so skip the autouse
# test_domain fixture and its initialization cost.
pytestmark = pytest.mark.no_test_domain

_REPO_ROOT = Path(__file__).resolve().parents[2]

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR
VALUE_OBJECT = SKILLS_ROOT / "value-object"

DOCS_SITE = "https://docs.proteanhq.com"
CHOOSING_ELEMENTS_URL = f"{DOCS_SITE}/concepts/building-blocks/choosing-element-types/"

# A markdown link target: the part inside "](...)".
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")


@pytest.mark.parametrize(
    "path",
    [
        VALUE_OBJECT / "SKILL.md",
        VALUE_OBJECT / REFERENCES_DIRNAME / "anti-patterns.md",
    ],
    ids=["SKILL.md", "anti-patterns.md"],
)
def test_value_object_skill_links_to_the_published_page(path: Path) -> None:
    assert f"[Deciding Between Elements]({CHOOSING_ELEMENTS_URL})" in path.read_text()


def test_published_url_maps_to_a_docs_source() -> None:
    page = urlparse(CHOOSING_ELEMENTS_URL).path.strip("/")
    assert page
    assert (_REPO_ROOT / "docs" / f"{page}.md").is_file()


def test_no_pack_file_uses_the_old_page_path() -> None:
    pack_files = sorted(p for p in PACK_ROOT.rglob("*") if p.is_file())
    assert pack_files
    offenders = [
        str(p.relative_to(PACK_ROOT))
        for p in pack_files
        if "deciding-between-elements" in p.read_text(errors="ignore")
    ]
    assert offenders == []


def test_every_relative_skill_link_resolves_inside_the_pack() -> None:
    skill_files = sorted(SKILLS_ROOT.rglob("*.md"))
    assert skill_files
    pack_root = PACK_ROOT.resolve()
    dead = []
    checked = 0
    for path in skill_files:
        for target in LINK_TARGET.findall(path.read_text()):
            if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            checked += 1
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            if not resolved.is_relative_to(pack_root) or not resolved.exists():
                dead.append(f"{path.relative_to(PACK_ROOT)}: {target}")
    assert checked
    assert dead == []
