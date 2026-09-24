"""Links from the DX pack to the published docs site.

The pack ships without the ``docs/`` tree, so a skill that points at a docs page
must use its published URL under ``https://docs.proteanhq.com``. These tests pin
the value-object skill's two "Deciding Between Elements" links and check that
every docs URL in the pack maps to a page in ``docs/``.

Relative links between pack files are checked against the rendered plugin tree
by ``tests/dx/test_plugin.py``.
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
_DOCS_ROOT = _REPO_ROOT / "docs"

PACK_ROOT = Path(str(dx.pack_files()))
VALUE_OBJECT = PACK_ROOT / dx.SKILLS_DIR / "value-object"

DOCS_SITE = "https://docs.proteanhq.com"
CHOOSING_ELEMENTS_URL = f"{DOCS_SITE}/concepts/building-blocks/choosing-element-types/"

# A docs-site URL, up to the end of the markdown link or the surrounding text.
DOCS_URL = re.compile(re.escape(DOCS_SITE) + r"/[^)\s\"'<>]*")


def _pack_markdown() -> list[Path]:
    files = sorted(PACK_ROOT.rglob("*.md"))
    assert files
    return files


def _docs_source(url: str) -> Path | None:
    """Return the ``docs/`` file that publishes at ``url``, or ``None``."""
    page = urlparse(url).path.strip("/")
    candidates = [_DOCS_ROOT / "index.md"] if not page else []
    candidates += [_DOCS_ROOT / f"{page}.md", _DOCS_ROOT / page / "index.md"]
    return next((c for c in candidates if c.is_file()), None)


@pytest.mark.parametrize(
    "path",
    [
        VALUE_OBJECT / "SKILL.md",
        VALUE_OBJECT / REFERENCES_DIRNAME / "anti-patterns.md",
    ],
    ids=["SKILL.md", "anti-patterns.md"],
)
def test_value_object_skill_links_to_the_published_page(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert f"[Deciding Between Elements]({CHOOSING_ELEMENTS_URL})" in text


def test_no_pack_file_uses_the_old_page_path() -> None:
    pack_files = sorted(p for p in PACK_ROOT.rglob("*") if p.is_file())
    assert pack_files
    offenders = [
        str(p.relative_to(PACK_ROOT))
        for p in pack_files
        if "deciding-between-elements" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []


def test_every_docs_url_in_the_pack_maps_to_a_docs_page() -> None:
    urls = {
        (path.relative_to(PACK_ROOT).as_posix(), url)
        for path in _pack_markdown()
        for url in DOCS_URL.findall(path.read_text(encoding="utf-8"))
    }
    assert (
        "skills/value-object/SKILL.md",
        CHOOSING_ELEMENTS_URL,
    ) in urls
    dead = sorted(f"{path}: {url}" for path, url in urls if _docs_source(url) is None)
    assert dead == []
