"""The add-saga-flow before/after assets against PROCESS_MANAGER_UNCLOSED.

``test_examples.py`` only inits each asset; it does not run ``check``. The
add-saga-flow skill teaches the fix for ``PROCESS_MANAGER_UNCLOSED``, so this
harness runs the diagnostic that ``check`` runs: it builds each asset's IR and
asserts the before asset reports the code and the after asset clears it.

Each asset is executed under its own ``run_name`` so the two domains' element
registrations land in separate namespaces and cannot collide (both assets define
same-named events and aggregates). The runner mirrors ``test_examples.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from protean import dx
from protean.domain import Domain
from protean.ir.builder import IRBuilder

# These build domains directly from package data; they never touch the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "add-saga-flow" / "assets"

# The runner executes an asset by path, so it needs the pack unpacked on disk.
# The accessor does not promise a filesystem root (a zip install would not have
# one); CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the saga assets are executed by path",
        allow_module_level=True,
    )


def _build_ir(asset_name: str, run_name: str) -> dict:
    """Run one saga asset, init its domain, and return its built IR."""
    namespace = runpy.run_path(str(ASSETS_DIR / asset_name), run_name=run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, f"{asset_name} must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return IRBuilder(domain).build()


def _findings(ir: dict, code: str) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


def test_before_asset_reports_process_manager_unclosed():
    ir = _build_ir("saga_before_unclosed.py", "_saga_before_")

    findings = _findings(ir, "PROCESS_MANAGER_UNCLOSED")
    assert len(findings) > 0, "the before asset must report PROCESS_MANAGER_UNCLOSED"
    finding = findings[0]
    # Pin the full FQN, run_name prefix included, so a cross-contaminated PM from
    # the after asset (``_saga_after_.OrderFulfillmentPM``) cannot satisfy this.
    assert finding["element"] == "_saga_before_.OrderFulfillmentPM"
    assert finding["level"] == "info"


def test_after_asset_clears_process_manager_unclosed():
    ir = _build_ir("saga_after_closed.py", "_saga_after_")

    assert _findings(ir, "PROCESS_MANAGER_UNCLOSED") == [], (
        "the after asset closes the saga with end=True handlers, so "
        "PROCESS_MANAGER_UNCLOSED must not fire"
    )
