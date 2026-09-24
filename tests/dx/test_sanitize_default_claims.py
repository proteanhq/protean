"""The ``sanitize`` default the field and validation skills teach.

``String`` and ``Text`` leave ``sanitize`` unset, which defers to the
domain-level ``[field_defaults] sanitize`` setting. Its framework default is
``False`` (``protean.domain.config``), so sanitization is opt-in. Every place
the add-field and add-validation references document ``sanitize`` must say the
default is off, name the domain-wide setting, and describe it as escaping
(``bleach.clean()`` keeps disallowed tags as escaped text). No skill may claim
the default is on.

``tests/dx/test_plugin.py`` only checks that the render matches the pack, so a
pack edit that brings back a "default True" claim would keep it green. This
test checks the claim itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean import dx
from protean.domain.config import _default_config
from protean.dx.pack import REFERENCES_DIR as REFERENCES_DIRNAME

# These tests read package data; they never touch a Domain, so skip the autouse
# test_domain fixture and its initialization cost.
pytestmark = pytest.mark.no_test_domain

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR

FIELD_TYPES = SKILLS_ROOT / "add-field" / REFERENCES_DIRNAME / "field-types.md"
VALIDATION = SKILLS_ROOT / "add-field" / REFERENCES_DIRNAME / "validation.md"
LAYER1 = (
    SKILLS_ROOT / "add-validation" / REFERENCES_DIRNAME / "layer1-field-constraints.md"
)

# Matches "default: True", "default is `True`", "defaults to True",
# "True by default" and "on by default".
DEFAULT_ON_CLAIM = re.compile(
    r"defaults?(?: is| to|:)?\s*`?(?:true|on)\b|\b(?:true|on)`? by default",
    re.IGNORECASE,
)


def _parameter_sites(path: Path) -> list[str]:
    """Lines that document the ``sanitize`` parameter, as list item or table row."""
    return [
        line
        for line in path.read_text().splitlines()
        if line.startswith(("- `sanitize`", "| `sanitize`"))
    ]


def _example_sites(path: Path) -> list[str]:
    """Each ``sanitize=True`` example line, joined with the comment above it."""
    lines = path.read_text().splitlines()
    return [
        f"{lines[i - 1]}\n{line}"
        for i, line in enumerate(lines)
        if "sanitize=True" in line and i > 0
    ]


def _sites() -> list[tuple[str, str]]:
    return [
        *(
            (f"{FIELD_TYPES.name}:{n}", s)
            for n, s in enumerate(_parameter_sites(FIELD_TYPES))
        ),
        *(
            (f"{VALIDATION.name}:{n}", s)
            for n, s in enumerate(_example_sites(VALIDATION))
        ),
        *((f"{LAYER1.name}:{n}", s) for n, s in enumerate(_parameter_sites(LAYER1))),
    ]


def test_framework_sanitize_default_is_off() -> None:
    assert _default_config()["field_defaults"]["sanitize"] is False


def test_every_documented_site_is_found() -> None:
    # String and Text in field-types.md, the example in validation.md, and the
    # table row in layer1-field-constraints.md.
    assert len(_parameter_sites(FIELD_TYPES)) == 2
    assert len(_example_sites(VALIDATION)) == 1
    assert len(_parameter_sites(LAYER1)) == 1


@pytest.mark.parametrize(("site", "text"), _sites(), ids=[s for s, _ in _sites()])
def test_site_says_the_default_is_off(site: str, text: str) -> None:
    assert re.search(r"default(?: is|:) off", text), text


@pytest.mark.parametrize(("site", "text"), _sites(), ids=[s for s, _ in _sites()])
def test_site_names_the_domain_wide_setting(site: str, text: str) -> None:
    assert "[field_defaults] sanitize" in text, text


@pytest.mark.parametrize(("site", "text"), _sites(), ids=[s for s, _ in _sites()])
def test_site_says_sanitizing_escapes_rather_than_strips(site: str, text: str) -> None:
    assert "strip" not in text.lower(), text


def test_no_skill_claims_sanitize_is_on_by_default() -> None:
    skill_files = sorted(SKILLS_ROOT.rglob("*.md"))
    assert skill_files
    checked = 0
    for path in skill_files:
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if "sanitize" not in line.lower():
                continue
            window = "\n".join(lines[max(i - 1, 0) : i + 2])
            assert not DEFAULT_ON_CLAIM.search(window), f"{path}:{i + 1}: {window}"
            checked += 1
    assert checked


@pytest.mark.parametrize(
    "claim",
    [
        "- `sanitize` (default: True)",
        "- `sanitize` (default: `True`)",
        "sanitize defaults to True",
        "sanitize is True by default",
        "sanitize is on by default",
        "Default is True",
    ],
)
def test_default_on_claim_pattern_catches_known_wordings(claim: str) -> None:
    assert DEFAULT_ON_CLAIM.search(claim)


@pytest.mark.parametrize(
    "text",
    [
        "- `sanitize` (default: off; set `True` per field)",
        "user_input: String(sanitize=True)  # Opt-in: the default is off",
    ],
)
def test_default_on_claim_pattern_passes_the_current_wording(text: str) -> None:
    assert not DEFAULT_ON_CLAIM.search(text)
