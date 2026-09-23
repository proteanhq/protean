"""The extract-bounded-context before/after assets: the diagnostic they teach.

``test_examples.py`` only inits each asset; it does not run ``check``. This
harness does: it builds each asset's IR, the way ``check`` does, and asserts the
extraction actually clears the smell it targets.

- The before asset is one ``Domain`` whose two clusters (``Order`` in sales,
  ``Shipment`` in fulfilment) reference each other, so ``check`` reports
  ``CIRCULAR_CLUSTER_DEPENDENCY`` on both. A cross-cluster ``Reference`` also
  trips ``CROSS_AGGREGATE_REFERENCE``; that is a co-smell the skill names, so the
  before asserts only the targeted code, not the absence of the others.
- The after asset splits the two into separate ``Domain`` objects that talk by a
  published event across the seam. Neither holds a ``Reference`` into the other,
  so ``check`` reports neither ``CIRCULAR_CLUSTER_DEPENDENCY`` nor
  ``CROSS_AGGREGATE_REFERENCE`` on either domain.

Each asset is executed under its own ``run_name`` so the two runs' element
registrations land in separate namespaces and cannot collide (both assets define
same-named events and aggregates). The runner mirrors ``test_examples.py`` and
``test_saga_flow_example.py``.
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
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "extract-bounded-context" / "assets"

CIRCULAR = "CIRCULAR_CLUSTER_DEPENDENCY"
CROSS_REFERENCE = "CROSS_AGGREGATE_REFERENCE"

# The runner executes an asset by path, so it needs the pack unpacked on disk.
# The accessor does not promise a filesystem root (a zip install would not have
# one); CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the extract-bounded-context assets are "
        "executed by path",
        allow_module_level=True,
    )


def _domains(asset_name: str, run_name: str) -> list[Domain]:
    """Run one asset and return the initialized domains it defines, in order."""
    namespace = runpy.run_path(str(ASSETS_DIR / asset_name), run_name=run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    for domain in domains:
        domain.init(traverse=False)
    return domains


def _findings(ir: dict, code: str) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


def test_before_asset_reports_circular_cluster_dependency():
    domains = _domains("extract_bounded_context_before.py", "_ebc_before_")
    assert len(domains) == 1, "the before asset is one Domain holding both contexts"
    ir = IRBuilder(domains[0]).build()

    findings = _findings(ir, CIRCULAR)
    elements = sorted(d["element"] for d in findings)
    # One diagnostic per participating cluster, both pinned to the run_name-
    # prefixed FQNs so a cross-contaminated after cluster cannot satisfy this.
    assert elements == ["_ebc_before_.Order", "_ebc_before_.Shipment"]
    for finding in findings:
        assert finding["level"] == "warning"


def test_after_asset_clears_the_targeted_codes_on_both_domains():
    domains = _domains("extract_bounded_context_after.py", "_ebc_after_")
    # Two separate contexts now: the sales domain and the fulfilment domain.
    assert len(domains) == 2, "the after asset splits the context into two Domains"

    for domain in domains:
        ir = IRBuilder(domain).build()
        assert _findings(ir, CIRCULAR) == [], (
            f"{domain.name} must not report {CIRCULAR}; the extraction removed the "
            "cross-context references that formed the cycle"
        )
        assert _findings(ir, CROSS_REFERENCE) == [], (
            f"{domain.name} must not report {CROSS_REFERENCE}; the seam now crosses "
            "by identity (order_id), with no Reference into the other context"
        )
