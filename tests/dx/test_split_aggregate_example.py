"""The split-aggregate before/after assets: the diagnostics, and the flow.

``test_examples.py`` only inits each asset; it does not run ``check`` and it
does not run the event-driven hop. This harness does both:

- It builds each asset's IR, the way ``check`` does, and asserts the before
  asset reports ``AGGREGATE_TOO_LARGE`` while the after asset clears both
  ``AGGREGATE_TOO_LARGE`` and ``CROSS_AGGREGATE_REFERENCE`` and carries no
  warning-level diagnostics of its own.
- It runs the after asset's flow: placing an order opens its shipment through a
  domain event, so the asset's claim that the two aggregates stay linked by
  identity and by an event holds.

Each asset is executed under its own ``run_name`` so the two domains' element
registrations land in separate namespaces and cannot collide (both assets define
same-named ``Order`` aggregates and entities). The runner mirrors
``test_examples.py`` and ``test_saga_flow_example.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.ir.builder import IRBuilder

# These build domains directly from package data; they never touch the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "split-aggregate" / "assets"

# The runner executes an asset by path, so it needs the pack unpacked on disk.
# The accessor does not promise a filesystem root (a zip install would not have
# one); CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the split assets are executed by path",
        allow_module_level=True,
    )


def _load(asset_name: str, run_name: str) -> tuple[dict[str, Any], Domain]:
    """Run one asset and return its namespace and its initialized domain."""
    namespace = runpy.run_path(str(ASSETS_DIR / asset_name), run_name=run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, f"{asset_name} must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return namespace, domain


def _build_ir(asset_name: str, run_name: str) -> dict:
    """Run one asset, init its domain, and return its built IR."""
    _, domain = _load(asset_name, run_name)
    return IRBuilder(domain).build()


def _findings(ir: dict, code: str) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


def _warnings(ir: dict) -> list[tuple[str, str]]:
    return [
        (d["code"], d["element"])
        for d in ir["diagnostics"]
        if d["level"] in ("warning", "error")
    ]


def test_before_asset_reports_aggregate_too_large():
    ir = _build_ir("split_order_before.py", "_split_before_")

    findings = _findings(ir, "AGGREGATE_TOO_LARGE")
    assert len(findings) > 0, "the before asset must report AGGREGATE_TOO_LARGE"
    finding = findings[0]
    # Pin the full FQN, run_name prefix included, so a cross-contaminated Order
    # from the after asset cannot satisfy this.
    assert finding["element"] == "_split_before_.Order"
    assert finding["level"] == "info"
    # The count is the signal the skill teaches: six entities over a limit of
    # five. Pin it so a before asset that drifts under the limit fails here.
    assert "6 entities" in finding["message"]


def test_before_asset_reports_no_warnings():
    """The before asset must isolate one smell. If it carried warnings of its own
    (an unhandled command, an aggregate no command reaches), a reader running
    ``check`` on it could not tell which finding the lesson is about."""
    ir = _build_ir("split_order_before.py", "_split_before_warnings_")

    assert _warnings(ir) == []


def test_after_asset_clears_aggregate_too_large():
    ir = _build_ir("split_order_after.py", "_split_after_")

    assert _findings(ir, "AGGREGATE_TOO_LARGE") == [], (
        "the after asset splits Order into two aggregates of three entities "
        "each, so AGGREGATE_TOO_LARGE must not fire"
    )


def test_after_asset_clears_cross_aggregate_reference():
    ir = _build_ir("split_order_after.py", "_split_after_xref_")

    assert _findings(ir, "CROSS_AGGREGATE_REFERENCE") == [], (
        "the after asset links Shipment to Order by an Identifier field, not a "
        "Reference, so CROSS_AGGREGATE_REFERENCE must not fire"
    )


def test_after_asset_reports_no_warnings():
    """The skill tells readers to resolve what ``check`` reports, so the asset it
    holds up as the fix must not leave warnings of its own: an unhandled event, a
    command with no handler, an aggregate with no write path, or a cross-cluster
    event handler (EVENT_HANDLER_FOREIGN_EVENT), which the event handler avoids by
    sitting in Order's own cluster."""
    ir = _build_ir("split_order_after.py", "_split_after_warnings_")

    assert _warnings(ir) == []


def test_after_asset_opens_the_shipment_by_identity():
    """The cross-aggregate link is a real domain event, not just prose. Placing
    an order raises OrderPlaced, the event handler issues OpenShipment, and
    Shipment's command handler opens a shipment carrying the order's id."""
    namespace, domain = _load("split_order_after.py", "_split_after_run_")

    with domain.domain_context():
        domain.process(
            namespace["PlaceOrder"](order_id="ORD-1", customer_id="CUST-1", total=100.0)
        )

        shipment = domain.repository_for(namespace["Shipment"])._dao.find_by(
            order_id="ORD-1"
        )

    # The shipment exists and carries the order's id by identity, which is the
    # whole point of the split: the two aggregates are linked by value, and the
    # link was driven by the OrderPlaced event, not by a direct reference.
    assert shipment.order_id == "ORD-1"
    assert shipment.status == "pending"
