"""Every ``kind="staleness"`` diagnostic code is documented in the staleness guide.

`docs/guides/compatibility-checking.md` documents the staleness hook and the
`IR_STALE` diagnostic that `staleness_diagnostic()` produces. Like the lint-code
guard (`tests/test_diagnostic_codes_are_documented.py`) and the raise-code guard
(`tests/test_init_diagnostics_are_documented.py`), this derives the code set from
`REGISTRY`, so a new staleness code that never reaches the guide fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.ir.diagnostics import REGISTRY

GUIDE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "guides"
    / "compatibility-checking.md"
)

pytestmark = pytest.mark.no_test_domain


def _staleness_codes() -> set[str]:
    """The ``kind="staleness"`` codes, produced by ``staleness_diagnostic()``."""
    return {code.value for code in REGISTRY if REGISTRY[code].kind == "staleness"}


class TestStalenessDiagnosticsAreDocumented:
    def test_the_guide_is_there(self):
        assert GUIDE.is_file(), f"{GUIDE} is missing"

    def test_there_are_staleness_codes_to_document(self):
        # Guards against a vacuous pass if the staleness kind ever empties out.
        assert _staleness_codes()

    def test_every_staleness_code_is_documented(self):
        text = GUIDE.read_text(encoding="utf-8")
        undocumented = {code for code in _staleness_codes() if code not in text}

        assert not undocumented, (
            "These staleness diagnostic codes are in the registry but are not "
            f"mentioned in {GUIDE.name}: {sorted(undocumented)}. Document each in "
            "the staleness section, alongside the resolving operation that clears "
            "it."
        )
