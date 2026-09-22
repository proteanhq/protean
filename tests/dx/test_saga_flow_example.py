"""The add-saga-flow before/after assets: the diagnostic, and the flow itself.

``test_examples.py`` only inits each asset; it does not run ``check`` and it
does not run the flow. This harness does both:

- It builds each asset's IR, the way ``check`` does, and asserts the before
  asset reports ``PROCESS_MANAGER_UNCLOSED`` while the after asset clears it and
  reports no warnings at all.
- It runs the after asset's saga end to end, on the success path and on the
  compensating failure path, so the asset's claim that the flow runs holds.

Each asset is executed under its own ``run_name`` so the two domains' element
registrations land in separate namespaces and cannot collide (both assets define
same-named events and aggregates). The runner mirrors ``test_examples.py``.
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
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "add-saga-flow" / "assets"

# The runner executes an asset by path, so it needs the pack unpacked on disk.
# The accessor does not promise a filesystem root (a zip install would not have
# one); CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the saga assets are executed by path",
        allow_module_level=True,
    )


def _load(asset_name: str, run_name: str) -> tuple[dict[str, Any], Domain]:
    """Run one saga asset and return its namespace and its initialized domain."""
    namespace = runpy.run_path(str(ASSETS_DIR / asset_name), run_name=run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, f"{asset_name} must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return namespace, domain


def _build_ir(asset_name: str, run_name: str) -> dict:
    """Run one saga asset, init its domain, and return its built IR."""
    _, domain = _load(asset_name, run_name)
    return IRBuilder(domain).build()


def _findings(ir: dict, code: str) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


def _saga_statuses(domain: Domain, pm_cls: type, order_id: str) -> list[str]:
    """The status the saga recorded at each transition, in order."""
    stream = f"{pm_cls.meta_.stream_category}-{order_id}"
    messages = domain.event_store.store.read(stream)
    return [message.to_domain_object().state["status"] for message in messages]


def _run_saga(namespace: dict[str, Any], domain: Domain, order_id: str, total: float):
    """Place an order, which runs the saga in-process, and return its statuses."""
    with domain.domain_context():
        domain.process(
            namespace["PlaceOrder"](
                order_id=order_id, customer_id="CUST-1", total=total
            )
        )
        return _saga_statuses(domain, namespace["OrderFulfillmentPM"], order_id)


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


def test_after_asset_reports_no_warnings():
    """The skill tells readers to resolve what ``check`` reports, so the asset it
    holds up as the fix must not leave warnings of its own: an unhandled command
    (UNUSED_COMMAND), or an aggregate that no command reaches
    (AGGREGATE_WITHOUT_COMMAND_HANDLER)."""
    ir = _build_ir("saga_after_closed.py", "_saga_after_warnings_")

    warnings = [d for d in ir["diagnostics"] if d["level"] in ("warning", "error")]
    assert warnings == [], [(d["code"], d["element"]) for d in warnings]


def test_after_asset_runs_the_success_path():
    namespace, domain = _load("saga_after_closed.py", "_saga_after_success_")

    statuses = _run_saga(namespace, domain, order_id="ORD-SUCCESS", total=100.0)

    # Each status comes from a different aggregate's event: "awaiting_payment"
    # from StockReserved, "shipping" from PaymentConfirmed, "fulfilled" from
    # ShipmentDispatched. The sequence is the whole flow having run.
    assert statuses == [
        "reserving_stock",
        "awaiting_payment",
        "shipping",
        "fulfilled",
    ]


def test_after_asset_runs_the_compensating_path():
    namespace, domain = _load("saga_after_closed.py", "_saga_after_failure_")

    # Over PAYMENT_LIMIT, so Payment raises PaymentFailed instead of confirming.
    statuses = _run_saga(namespace, domain, order_id="ORD-FAILED", total=900.0)

    assert statuses == ["reserving_stock", "awaiting_payment", "cancelled"]

    with domain.domain_context():
        stream = f"{namespace['OrderFulfillmentPM'].meta_.stream_category}-ORD-FAILED"
        final = domain.event_store.store.read(stream)[-1].to_domain_object()

        # Both compensating commands ran: the reservation is released and the
        # order is cancelled.
        reservation = domain.repository_for(namespace["Inventory"]).get(
            final.state["reservation_id"]
        )
        assert reservation.status == "released"

        order = domain.repository_for(namespace["Order"]).get("ORD-FAILED")
        assert order.status == "cancelled"


def test_before_asset_runs_the_flow_without_closing_it():
    """The before asset is the same flow, only left open: it still reaches
    "fulfilled", which is why the missing end=True is easy to miss."""
    namespace, domain = _load("saga_before_unclosed.py", "_saga_before_run_")

    statuses = _run_saga(namespace, domain, order_id="ORD-OPEN", total=100.0)

    assert statuses == [
        "reserving_stock",
        "awaiting_payment",
        "shipping",
        "fulfilled",
    ]
