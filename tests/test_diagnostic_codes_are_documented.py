"""Every ``kind="lint"`` diagnostic code has an entry in the published catalog.

`docs/reference/fitness-functions.md` is hand-maintained, so a rule can reach
the registry without reaching the reference. That is what happened to
`ADAPTER_CALL_IN_DOMAIN`, `UNINDEXED_FILTER_PATH`, and `LOW_POOL_SIZE`. Two of
them already had deep-dive pages under `docs/concepts/protean-check/rules/`,
and the catalog still listed neither.

The catalog is the documented public surface for `protean check`, so a lint
code missing from it is a code an operator cannot look up. The ``kind="raise"``
codes are carried on exceptions, not emitted by `protean check`, so they live in
`docs/reference/init-diagnostics.md` instead and are guarded by
`tests/test_init_diagnostics_are_documented.py`.
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


def _lint_codes() -> set[str]:
    """The ``kind="lint"`` codes — the ones `protean check` emits and this
    catalog documents. ``kind="raise"`` codes are documented elsewhere."""
    return {code.value for code in REGISTRY if REGISTRY[code].kind == "lint"}


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
        undocumented = _lint_codes() - _catalogued()

        assert not undocumented, (
            "These lint diagnostic codes are in the registry but have no `### "
            "CODE` entry in docs/reference/fitness-functions.md: "
            f"{sorted(undocumented)}. Add one under the section matching the "
            "code's category, following the Category/Level table plus "
            "**Why.**/**Fix.** shape the other entries use."
        )

    def test_the_catalog_documents_no_unregistered_code(self):
        stale = _catalogued() - _lint_codes()

        assert not stale, (
            "docs/reference/fitness-functions.md documents codes that are no "
            f"longer registered lint codes: {sorted(stale)}. Remove the entries, "
            "or restore the codes if the removal was accidental. (raise-kind "
            "codes belong in docs/reference/init-diagnostics.md.)"
        )
