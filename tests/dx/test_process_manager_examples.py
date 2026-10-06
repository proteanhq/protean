"""Every process-manager asset closes its flow with an ``end=True`` handler.

``PROCESS_MANAGER_UNCLOSED`` is an info-level diagnostic, and
``test_asset_diagnostics.py`` only holds findings at warning level and above, so
it cannot see this one. A flow that calls ``mark_as_complete()`` without an
``end=True`` handler trips it. This test runs ``Domain.check(traverse=False)``
on each asset and reads diagnostics at every level.

Each asset runs under its own ``run_name`` so the domains' registrations stay in
separate namespaces.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from protean import dx
from protean.domain import Domain
from protean.ir.builder import IRBuilder
from protean.utils import DomainObjects

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "process-manager" / "assets"

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the process-manager assets are executed by path",
        allow_module_level=True,
    )

ASSETS = sorted(
    path.name for path in ASSETS_DIR.glob("*.py") if path.name != "__init__.py"
)


def test_the_asset_list_is_not_empty():
    assert len(ASSETS) >= 4


@pytest.mark.parametrize("asset", ASSETS)
def test_asset_reports_no_unclosed_process_manager(asset):
    namespace = runpy.run_path(
        str(ASSETS_DIR / asset), run_name=f"pm_example_{asset[:-3]}"
    )
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, f"{asset} must define exactly one Domain"
    domain = domains[0]

    report = domain.check(traverse=False)

    # ``check`` leaves ``diagnostics`` empty when validation fails or the IR
    # does not build, so prove both before reading the diagnostics.
    assert report["errors"] == []
    assert domain.registry._elements[DomainObjects.PROCESS_MANAGER.value]
    IRBuilder(domain).build()

    unclosed = [
        d for d in report["diagnostics"] if d["code"] == "PROCESS_MANAGER_UNCLOSED"
    ]
    assert unclosed == []
