"""Every registered diagnostic code has an entry in the published catalog.

`docs/reference/fitness-functions.md` is hand-maintained, so a rule can reach
the registry without reaching the reference. That is what happened to
`ADAPTER_CALL_IN_DOMAIN`, `UNINDEXED_FILTER_PATH`, and `LOW_POOL_SIZE`. Two of
them already had deep-dive pages under `docs/concepts/protean-check/rules/`,
and the catalog still listed neither.

The catalog is the documented public surface for `protean check`, so a code
missing from it is a code an operator cannot look up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean.ir.diagnostics import REGISTRY

CATALOG = (
    Path(__file__).resolve().parents[1] / "docs" / "reference" / "fitness-functions.md"
)

pytestmark = pytest.mark.no_test_domain


def _catalogued() -> set[str]:
    """Codes carrying an `### CODE_NAME` heading in the catalog."""
    return set(
        re.findall(
            r"^###\s+([A-Z][A-Z_0-9]*)", CATALOG.read_text(encoding="utf-8"), flags=re.M
        )
    )


class TestDiagnosticCodesAreDocumented:
    def test_the_catalog_is_there(self):
        assert CATALOG.is_file(), f"{CATALOG} is missing"

    def test_every_registered_code_is_catalogued(self):
        undocumented = {code.value for code in REGISTRY} - _catalogued()

        assert not undocumented, (
            "These diagnostic codes are in the registry but have no `### CODE` "
            f"entry in docs/reference/fitness-functions.md: {sorted(undocumented)}. "
            "Add one under the section matching the code's category, following "
            "the Category/Level table plus **Why.**/**Fix.** shape the other "
            "entries use."
        )

    def test_the_catalog_documents_no_unregistered_code(self):
        stale = _catalogued() - {code.value for code in REGISTRY}

        assert not stale, (
            "docs/reference/fitness-functions.md documents codes that are no "
            f"longer in the registry: {sorted(stale)}. Remove the entries, or "
            "restore the codes if the removal was accidental."
        )
