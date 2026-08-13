"""Every ``kind="raise"`` diagnostic code has an entry in the init-diagnostics
catalog.

`docs/reference/init-diagnostics.md` is hand-maintained, so a coded exception can
reach the registry without reaching the reference. This guard mirrors
`tests/test_diagnostic_codes_are_documented.py` (which covers the `kind="lint"`
codes against the fitness-function catalog) for the raise codes: it derives one
side from `REGISTRY` and the other by parsing the doc, and asserts both
directions, so neither an undocumented new code nor a stale doc entry slips
through.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean.ir.diagnostics import REGISTRY

CATALOG = (
    Path(__file__).resolve().parents[1] / "docs" / "reference" / "init-diagnostics.md"
)

pytestmark = pytest.mark.no_test_domain


def _raise_codes() -> set[str]:
    return {code.value for code in REGISTRY if REGISTRY[code].kind == "raise"}


def _catalogued() -> set[str]:
    """Codes carrying an `### CODE_NAME` heading in the catalog."""
    return set(
        re.findall(
            r"^###\s+([A-Z][A-Z_0-9]*)", CATALOG.read_text(encoding="utf-8"), flags=re.M
        )
    )


class TestInitDiagnosticsAreDocumented:
    def test_the_catalog_is_there(self):
        assert CATALOG.is_file(), f"{CATALOG} is missing"

    def test_there_are_raise_codes_to_document(self):
        # Guards against a vacuous pass if every code became lint.
        assert _raise_codes()

    def test_every_raise_code_is_catalogued(self):
        undocumented = _raise_codes() - _catalogued()

        assert not undocumented, (
            "These raise-kind diagnostic codes are in the registry but have no "
            "`### CODE` entry in docs/reference/init-diagnostics.md: "
            f"{sorted(undocumented)}. Add one under the section matching the "
            "code's category, following the Category/Level/Exception/Raised-by "
            "table plus **Why.**/**Fix.** shape the other entries use."
        )

    def test_the_catalog_documents_no_unregistered_code(self):
        stale = _catalogued() - _raise_codes()

        assert not stale, (
            "docs/reference/init-diagnostics.md documents codes that are no "
            f"longer registered raise codes: {sorted(stale)}. Remove the "
            "entries, or restore the codes if the removal was accidental. (lint "
            "codes belong in docs/reference/fitness-functions.md.)"
        )
