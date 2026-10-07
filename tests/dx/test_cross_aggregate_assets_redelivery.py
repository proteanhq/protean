"""Every asset that reacts to another aggregate's event: the flow, and redelivery.

``test_cross_aggregate_flow_example.py`` covers the main cross-sync asset in
detail. This module runs the same two checks over every asset that hands off
to another aggregate with a command:

- Driving the source step changes the target aggregate as the asset says, so
  the hop from event handler to command handler runs.
- Redelivering every stored event, newest first, leaves every aggregate as it
  was. Events are delivered at least once and can arrive late, so each
  receiving command handler must skip work it has already applied.

Each asset runs under its own ``run_name`` so registrations cannot collide.
"""

from __future__ import annotations

import runpy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.utils.sync_dispatch import dispatch_events_sync

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the assets are executed by path",
        allow_module_level=True,
    )

Namespace = dict[str, Any]


def _all(ns: Namespace, domain: Domain, name: str) -> list[Any]:
    return domain.repository_for(ns[name])._dao.query.all().items


def _cross_sync_order_inventory(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Inventory"]).add(
        ns["Inventory"](product_id="SKU-1", stock_level=10)
    )
    for quantity in (3, 3):
        order = ns["Order"](product_id="SKU-1", quantity=quantity)
        domain.repository_for(ns["Order"]).add(order)
        domain.process(ns["ShipOrder"](order_id=order.id))

    [inventory] = _all(ns, domain, "Inventory")
    assert inventory.stock_level == 4


def _cross_sync_multi_event(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["TeamMember"]).add(
        ns["TeamMember"](member_id="M-1", name="Alice")
    )
    first = ns["Task"](title="Write docs")
    second = ns["Task"](title="Review docs")
    domain.repository_for(ns["Task"]).add(first)
    domain.repository_for(ns["Task"]).add(second)
    domain.process(ns["AssignTask"](task_id=first.id, assignee_id="M-1"))
    domain.process(ns["AssignTask"](task_id=second.id, assignee_id="M-1"))
    domain.process(ns["UnassignTask"](task_id=second.id))
    domain.process(ns["AssignTask"](task_id=second.id, assignee_id="M-1"))
    domain.process(ns["CompleteTask"](task_id=first.id))

    member = domain.repository_for(ns["TeamMember"]).get("M-1")
    assert (member.assigned_count, member.completed_count) == (1, 1)


def _cross_sync_payment_subscription(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Subscription"]).add(
        ns["Subscription"](customer_id="CUST-1", plan_name="basic")
    )
    domain.process(
        ns["ConfirmPayment"](customer_id="CUST-1", amount=20.0, plan_name="pro")
    )
    domain.process(
        ns["ConfirmPayment"](customer_id="CUST-1", amount=50.0, plan_name="team")
    )

    [subscription] = _all(ns, domain, "Subscription")
    assert (subscription.status, subscription.plan_name) == ("active", "team")


def _event_handler_cross_aggregate(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Inventory"]).add(
        ns["Inventory"](book_id="BOOK-1", in_stock=100)
    )
    for quantity in (10, 10):
        order = ns["Order"](book_id="BOOK-1", quantity=quantity, total_amount=100)
        domain.repository_for(ns["Order"]).add(order)
        domain.process(ns["ShipOrder"](order_id=order.id))

    [inventory] = _all(ns, domain, "Inventory")
    assert inventory.in_stock == 80


def _event_handler_error_handling(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Shipment"]).add(
        ns["Shipment"](shipment_id="SHP-001", order_id="ORD-001", carrier="FedEx")
    )
    domain.process(ns["DispatchShipment"](shipment_id="SHP-001"))

    assert [log.log_id for log in _all(ns, domain, "ShipmentLog")] == [
        "SHP-001:dispatched"
    ]


def _event_handler_multiple_events(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Account"]).add(
        ns["Account"](account_id="ACC-001", email="alice@example.com", name="Alice")
    )
    domain.process(ns["RegisterAccount"](account_id="ACC-001"))
    domain.process(ns["SuspendAccount"](account_id="ACC-001", reason="first"))
    domain.process(ns["ReactivateAccount"](account_id="ACC-001"))
    domain.process(ns["SuspendAccount"](account_id="ACC-001", reason="second"))

    assert sorted(n.notification_type for n in _all(ns, domain, "Notification")) == [
        "reactivation",
        "suspension",
        "suspension",
        "welcome",
    ]


def _add_event_cross_aggregate(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Inventory"]).add(
        ns["Inventory"](product_id="PROD-100", in_stock=50)
    )
    for order_id in ("ORD-001", "ORD-002"):
        order = ns["Order"](order_id=order_id, product_id="PROD-100", quantity=5)
        order.ship()
        domain.repository_for(ns["Order"]).add(order)

    [inventory] = _all(ns, domain, "Inventory")
    assert inventory.in_stock == 40


def _add_event_multiple_events(ns: Namespace, domain: Domain) -> None:
    repo = domain.repository_for(ns["Shipment"])
    shipment = ns["Shipment"](shipment_id="SHIP-001", order_id="ORD-001", carrier="UPS")
    shipment.dispatch()
    repo.add(shipment)
    shipment = repo.get("SHIP-001")
    shipment.deliver(delivered_at=datetime.now(UTC))
    repo.add(shipment)

    assert repo.get("SHIP-001").tracking_info == "DELIVERED-SHIP-001"
    assert len(_all(ns, domain, "Notification")) == 2


def _use_case_with_update(ns: Namespace, domain: Domain) -> None:
    domain.process(ns["CreateTicket"](title="Printer jam", reporter="bob"))
    [ticket] = _all(ns, domain, "Ticket")
    domain.process(ns["AssignTicket"](ticket_id=ticket.id, assignee="alice"))
    domain.process(ns["AssignTicket"](ticket_id=ticket.id, assignee="carol"))

    assert sorted(entry.detail for entry in _all(ns, domain, "AuditEntry")) == [
        "Assigned to alice",
        "Assigned to carol",
    ]


def _introduce_events_ecommerce_after(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Inventory"]).add(
        ns["Inventory"](product_id="WIDGET-01", available=100)
    )
    domain.repository_for(ns["CustomerNotification"]).add(
        ns["CustomerNotification"](customer_id="CUST-001")
    )
    for quantity in (5, 7):
        domain.process(
            ns["PlaceEcommerceOrder"](
                customer_id="CUST-001", product_id="WIDGET-01", quantity=quantity
            )
        )

    inventory = domain.repository_for(ns["Inventory"]).get("WIDGET-01")
    assert inventory.available == 88
    notification = domain.repository_for(ns["CustomerNotification"]).get("CUST-001")
    assert notification.last_message == "Order for 7x WIDGET-01 placed!"


def _audit_sample_refactored(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Inventory"]).add(
        ns["Inventory"](product_id="PROD-001", quantity_available=10)
    )
    for _ in range(2):
        domain.process(
            ns["PlaceOrder"](
                customer_id="CUST-001",
                product_id="PROD-001",
                quantity=2,
                unit_price=29.99,
            )
        )

    inventory = domain.repository_for(ns["Inventory"]).get("PROD-001")
    assert inventory.quantity_available == 6


def _scaffold_event_driven_flow(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Inventory"]).add(
        ns["Inventory"](product_id="p-1", available=100, reserved=0)
    )
    for quantity in (10, 10):
        order = ns["Order"].place(
            customer_id="c-1", product_id="p-1", quantity=quantity
        )
        domain.repository_for(ns["Order"]).add(order)

    [inventory] = _all(ns, domain, "Inventory")
    assert (inventory.available, inventory.reserved) == (80, 20)


def _coverage_domain_with_gaps(ns: Namespace, domain: Domain) -> None:
    domain.process(ns["CreateTicket"](title="Login fails", priority_level="high"))
    domain.process(ns["CreateTicket"](title="Typo on page"))

    assert sorted(log.message for log in _all(ns, domain, "NotificationLog")) == [
        "New ticket: Login fails (priority: high)",
        "New ticket: Typo on page (priority: low)",
    ]


SCENARIOS: dict[str, Callable[[Namespace, Domain], None]] = {
    "event-handler/assets/cross_sync_order_inventory.py": _cross_sync_order_inventory,
    "event-handler/assets/cross_sync_multi_event.py": _cross_sync_multi_event,
    "event-handler/assets/cross_sync_payment_subscription.py": (
        _cross_sync_payment_subscription
    ),
    "event-handler/assets/event_handler_cross_aggregate.py": (
        _event_handler_cross_aggregate
    ),
    "event-handler/assets/event_handler_error_handling.py": (
        _event_handler_error_handling
    ),
    "event-handler/assets/event_handler_multiple_events.py": (
        _event_handler_multiple_events
    ),
    "add-event/assets/add_event_cross_aggregate.py": _add_event_cross_aggregate,
    "add-event/assets/add_event_multiple_events.py": _add_event_multiple_events,
    "add-use-case/assets/use_case_with_update.py": _use_case_with_update,
    "refactor-introduce-events/assets/introduce_events_ecommerce_after.py": (
        _introduce_events_ecommerce_after
    ),
    "audit-domain/assets/audit_sample_refactored.py": _audit_sample_refactored,
    "generate-test-scaffold/assets/scaffold_event_driven_flow.py": (
        _scaffold_event_driven_flow
    ),
    "coverage-analysis/assets/coverage_domain_with_gaps.py": (
        _coverage_domain_with_gaps
    ),
}


def _load(asset: str) -> tuple[Namespace, Domain]:
    """Run the asset with synchronous processing and return its domain."""
    run_name = "_redelivery_" + Path(asset).stem + "_"
    ns = runpy.run_path(str(SKILLS / asset), run_name=run_name)
    domains = [value for value in ns.values() if isinstance(value, Domain)]
    assert len(domains) == 1, "the asset must define exactly one Domain"
    domain = domains[0]
    # The generate-test-scaffold asset leaves these to its conftest.
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"
    domain.init(traverse=False)
    return ns, domain


def _snapshot(domain: Domain) -> dict[str, list[dict[str, Any]]]:
    """Every record of every aggregate the asset defines."""
    snapshot = {}
    for name, record in domain.registry.aggregates.items():
        items = domain.repository_for(record.cls)._dao.query.all().items
        snapshot[name] = sorted(
            (item.to_dict() for item in items), key=lambda d: repr(sorted(d.items()))
        )
    return snapshot


def _stored_events(domain: Domain) -> list[BaseEvent]:
    messages = domain.event_store.store.read("$all")
    objects = [message.to_domain_object() for message in messages]
    return [obj for obj in objects if isinstance(obj, BaseEvent)]


@pytest.mark.parametrize("asset", sorted(SCENARIOS))
def test_redelivering_every_event_changes_nothing(asset: str) -> None:
    ns, domain = _load(asset)

    with domain.domain_context():
        SCENARIOS[asset](ns, domain)
        before = _snapshot(domain)
        events = _stored_events(domain)
        assert events, "the scenario must raise at least one event"

        for event in reversed(events):
            dispatch_events_sync([event], domain.handlers_for)

        assert _snapshot(domain) == before


def test_every_rewritten_asset_has_a_scenario() -> None:
    """A new asset that hands off to another aggregate needs a scenario here."""
    handing_off = sorted(
        str(path.relative_to(SKILLS))
        for path in SKILLS.glob("*/assets/*.py")
        if "current_domain.process(" in path.read_text()
        and "@domain.event_handler(part_of=" in path.read_text()
        and path.parent.parent.name not in ("split-aggregate", "add-saga-flow")
    )
    assert handing_off, "the pack must contain assets that hand off with a command"
    assert [asset for asset in handing_off if asset not in SCENARIOS] == []
