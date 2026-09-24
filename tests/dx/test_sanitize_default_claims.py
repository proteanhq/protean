"""The ``sanitize`` default the field and validation skills teach.

``String`` and ``Text`` leave ``sanitize`` unset, which defers to the
domain-level ``[field_defaults] sanitize`` setting. Its framework default is
``False`` (``protean.domain.config``), so sanitization is opt-in. The
add-field and add-validation references each state that default, and each
must say it is off and name the domain-wide setting.

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

SANITIZE_REFERENCES = (
    SKILLS_ROOT / "add-field" / REFERENCES_DIRNAME / "field-types.md",
    SKILLS_ROOT / "add-field" / REFERENCES_DIRNAME / "validation.md",
    SKILLS_ROOT / "add-validation" / REFERENCES_DIRNAME / "layer1-field-constraints.md",
)

DEFAULT_TRUE_CLAIM = re.compile(r"default(?: is|:)? true", re.IGNORECASE)


def test_framework_sanitize_default_is_off() -> None:
    assert _default_config()["field_defaults"]["sanitize"] is False


@pytest.mark.parametrize("path", SANITIZE_REFERENCES, ids=lambda p: p.name)
def test_reference_does_not_claim_sanitize_defaults_to_true(path: Path) -> None:
    sanitize_lines = [
        line for line in path.read_text().splitlines() if "sanitize" in line
    ]
    assert sanitize_lines, f"{path.name} no longer mentions sanitize"
    for line in sanitize_lines:
        assert not DEFAULT_TRUE_CLAIM.search(line), line


@pytest.mark.parametrize("path", SANITIZE_REFERENCES, ids=lambda p: p.name)
def test_reference_names_the_domain_wide_setting(path: Path) -> None:
    assert "[field_defaults] sanitize" in path.read_text()
