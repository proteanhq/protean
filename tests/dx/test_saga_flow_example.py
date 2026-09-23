"""The add-saga-flow before/after assets: the diagnostic, and the flow itself.

``test_examples.py`` only inits each asset; it does not run ``check`` and it
does not run the flow. This harness does both:

- It builds each asset's IR, the way ``check`` does, and asserts the before
  asset reports ``PROCESS_MANAGER_UNCLOSED`` while the after asset clears it and
  reports no warnings at all.
- It runs each asset's saga end to end, on the success path and on the
  compensating failure path, so the asset's claim that the flow runs holds.
- It pins the pair as a minimal diff: the two assets' executable code differs by
  the two ``end=True`` markers and by nothing else. That is what the skill says
  the before asset is, and it drifted once already.

Each asset is executed under its own ``run_name`` so the two domains' element
registrations land in separate namespaces and cannot collide (both assets define
same-named events and aggregates). The runner mirrors ``test_examples.py``.
"""

from __future__ import annotations

import ast
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


def _final_transition(domain: Domain, pm_cls: type, order_id: str):
    """The last transition the saga wrote for this instance."""
    stream = f"{pm_cls.meta_.stream_category}-{order_id}"
    return domain.event_store.store.read(stream)[-1].to_domain_object()


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


def test_before_asset_reports_no_warnings():
    """The before asset must isolate one diagnostic. If it carries warnings of
    its own (an unhandled command, an aggregate no command reaches), a reader
    running ``check`` on it cannot tell which finding the lesson is about."""
    ir = _build_ir("saga_before_unclosed.py", "_saga_before_warnings_")

    warnings = [d for d in ir["diagnostics"] if d["level"] in ("warning", "error")]
    assert warnings == [], [(d["code"], d["element"]) for d in warnings]


def _code_only(asset_name: str, drop_end: bool = False) -> str:
    """One asset's executable code, with every docstring dropped.

    Parsed structure, not text, so rewording a docstring or reflowing a comment
    does not register while a one-token change to the code does. With
    ``drop_end``, every ``end=True`` argument to ``@handle`` goes too, which is
    what lets the two assets be compared on everything except the markers.
    """
    tree = ast.parse((ASSETS_DIR / asset_name).read_bytes())
    for node in ast.walk(tree):
        if drop_end and isinstance(node, ast.Call):
            node.keywords = [
                k
                for k in node.keywords
                if not (
                    k.arg == "end"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value is True
                )
            ]
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree)


def _end_marker_count(asset_name: str) -> int:
    """How many handlers the asset marks ``end=True``."""
    tree = ast.parse((ASSETS_DIR / asset_name).read_bytes())
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for k in node.keywords
        if k.arg == "end"
        and isinstance(k.value, ast.Constant)
        and k.value.value is True
    )


def test_the_assets_differ_only_by_the_end_markers():
    """SKILL.md calls the before asset "the flow with the terminal handlers
    removed" and tells the reader the fix is to mark a terminating handler on the
    success path and on the failure path. Both sentences are only true while the
    pair is a minimal diff.

    It was not one. The before asset also dropped ``PaymentFailed``, both
    compensating commands and their handlers, ``Order.cancel``,
    ``Inventory.release``, ``PAYMENT_LIMIT``, the payment branch and the saga's
    ``reservation_id``: 87 lines, so the pair taught several changes at once and
    the prescribed fix could not be carried out on it at all. Nothing caught the
    drift, because no test compared the two.
    """
    # Ignore the markers on both sides: everything that is left must match.
    assert _code_only("saga_before_unclosed.py", drop_end=True) == _code_only(
        "saga_after_closed.py", drop_end=True
    ), (
        "the before asset must be the after asset with the two end=True markers "
        "removed and nothing else changed"
    )

    # And the markers are the difference: two on the after asset, one per
    # terminal path, none on the before asset.
    assert _end_marker_count("saga_after_closed.py") == 2
    assert _end_marker_count("saga_before_unclosed.py") == 0


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

    with domain.domain_context():
        final = _final_transition(
            domain, namespace["OrderFulfillmentPM"], "ORD-SUCCESS"
        )

    # The success terminal is marked end=True, so the saga closes here. Without
    # this the test passes on the status alone, and dropping end=True from
    # on_shipment_dispatched would go unnoticed.
    assert final.is_complete is True


def test_after_asset_runs_the_compensating_path():
    namespace, domain = _load("saga_after_closed.py", "_saga_after_failure_")

    # Over PAYMENT_LIMIT, so Payment raises PaymentFailed instead of confirming.
    statuses = _run_saga(namespace, domain, order_id="ORD-FAILED", total=900.0)

    assert statuses == ["reserving_stock", "awaiting_payment", "cancelled"]

    with domain.domain_context():
        final = _final_transition(domain, namespace["OrderFulfillmentPM"], "ORD-FAILED")

        # The failure terminal is marked end=True too, so the compensating path
        # closes the saga as well. PROCESS_MANAGER_UNCLOSED cannot catch a
        # missing end=True here, because the success terminal already clears it.
        assert final.is_complete is True

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

    with domain.domain_context():
        final = _final_transition(domain, namespace["OrderFulfillmentPM"], "ORD-OPEN")

    # No handler is marked end=True and none calls mark_as_complete(), so the
    # instance stays open after the flow has run to its last step.
    assert final.is_complete is False


def test_before_asset_compensates_without_closing_either():
    """The failure terminal is the half the before asset used to be missing. It
    runs the same compensation as the after asset and leaves the saga open too,
    so neither terminal closes and the diagnostic is about the markers alone."""
    namespace, domain = _load("saga_before_unclosed.py", "_saga_before_failure_")

    # Over PAYMENT_LIMIT, so Payment raises PaymentFailed instead of confirming.
    statuses = _run_saga(namespace, domain, order_id="ORD-OPEN-FAIL", total=900.0)

    assert statuses == ["reserving_stock", "awaiting_payment", "cancelled"]

    with domain.domain_context():
        final = _final_transition(
            domain, namespace["OrderFulfillmentPM"], "ORD-OPEN-FAIL"
        )
        assert final.is_complete is False

        # The compensation itself is unchanged from the after asset.
        reservation = domain.repository_for(namespace["Inventory"]).get(
            final.state["reservation_id"]
        )
        assert reservation.status == "released"

        order = domain.repository_for(namespace["Order"]).get("ORD-OPEN-FAIL")
        assert order.status == "cancelled"
