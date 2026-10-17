"""Run the examples on ``docs/patterns/coordinating-long-running-processes.md``.

Events are handed to the process manager with ``_handle()``, the way the engine
delivers them. The tests read the transitions the process manager wrote to its
own stream, and the commands it wrote to the command streams. Command
processing stays asynchronous, so an issued command is stored and not run.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("patterns/coordinating-long-running-processes/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def transitions(module, order_id):
    pm = module.OrderFulfillmentPM
    stream = f"{pm.meta_.stream_category}-{order_id}"
    return [
        message.to_domain_object()
        for message in module.domain.event_store.store.read(stream)
    ]


def issued_commands(module, order_id):
    """The commands for ``order_id``, in the order the process manager issued them."""
    commands = [
        message.to_domain_object()
        for message in module.domain.event_store.store.read("$all")
        if ":command-" in message.metadata.headers.stream
    ]
    return [type(c).__name__ for c in commands if c.order_id == order_id]


def deliver(module, *events):
    for event in events:
        module.OrderFulfillmentPM._handle(event)


def start_and_reserve(ex, order_id):
    deliver(
        ex,
        ex.OrderPlaced(order_id=order_id, customer_id="c-1", total=50.0),
        ex.InventoryReserved(order_id=order_id, product_id="p-1"),
    )


def test_happy_path_ends_completed(example):
    ex = example
    start_and_reserve(ex, "ord-1")
    deliver(
        ex,
        ex.PaymentConfirmed(payment_id="pay-1", order_id="ord-1", amount=50.0),
        ex.ShipmentCreated(shipment_id="shp-1", order_id="ord-1"),
        ex.ShipmentDelivered(shipment_id="shp-1", order_id="ord-1"),
    )

    steps = transitions(ex, "ord-1")
    assert [t.state["status"] for t in steps] == [
        "awaiting_inventory",
        "awaiting_payment",
        "awaiting_shipment",
        "awaiting_delivery",
        "completed",
    ]
    assert [t.is_complete for t in steps] == [False, False, False, False, True]
    final = steps[-1].state
    assert final["order_id"] == "ord-1"
    assert final["payment_id"] == "pay-1"
    assert final["shipment_id"] == "shp-1"
    assert issued_commands(ex, "ord-1") == [
        "ReserveInventory",
        "RequestPayment",
        "CreateShipment",
    ]


def test_a_completed_process_skips_later_events(example):
    ex = example
    start_and_reserve(ex, "ord-2")
    deliver(
        ex,
        ex.PaymentConfirmed(payment_id="pay-2", order_id="ord-2", amount=50.0),
        ex.ShipmentCreated(shipment_id="shp-2", order_id="ord-2"),
        ex.ShipmentDelivered(shipment_id="shp-2", order_id="ord-2"),
    )
    before = len(transitions(ex, "ord-2"))

    deliver(ex, ex.ShipmentRejected(shipment_id="shp-2", order_id="ord-2"))

    assert len(transitions(ex, "ord-2")) == before
    assert "RefundPayment" not in issued_commands(ex, "ord-2")


def test_duplicate_payment_confirmed_issues_one_shipment(example):
    ex = example
    start_and_reserve(ex, "ord-3")
    confirmed = ex.PaymentConfirmed(payment_id="pay-3", order_id="ord-3", amount=50.0)

    deliver(ex, confirmed, confirmed)

    assert transitions(ex, "ord-3")[-1].state["status"] == "awaiting_shipment"
    assert issued_commands(ex, "ord-3").count("CreateShipment") == 1


def test_payment_failure_compensates_and_ends(example):
    ex = example
    start_and_reserve(ex, "ord-4")

    deliver(
        ex, ex.PaymentFailed(payment_id="pay-4", order_id="ord-4", reason="declined")
    )

    last = transitions(ex, "ord-4")[-1]
    assert last.state["status"] == "cancelled"
    assert last.is_complete is True
    assert issued_commands(ex, "ord-4") == [
        "ReserveInventory",
        "RequestPayment",
        "ReleaseInventory",
        "CancelOrder",
    ]

    deliver(ex, ex.PaymentConfirmed(payment_id="pay-4", order_id="ord-4", amount=50.0))
    assert "CreateShipment" not in issued_commands(ex, "ord-4")


def test_shipment_rejected_unwinds_every_forward_step(example):
    ex = example
    start_and_reserve(ex, "ord-5")
    deliver(
        ex,
        ex.PaymentConfirmed(payment_id="pay-5", order_id="ord-5", amount=50.0),
        ex.ShipmentRejected(shipment_id="shp-5", order_id="ord-5", reason="no route"),
    )

    last = transitions(ex, "ord-5")[-1]
    assert last.state["status"] == "cancelled"
    assert last.is_complete is True
    assert issued_commands(ex, "ord-5")[-3:] == [
        "RefundPayment",
        "ReleaseInventory",
        "CancelOrder",
    ]


def test_timeout_compensates_the_steps_taken_so_far(example):
    ex = example
    start_and_reserve(ex, "ord-6")
    deliver(
        ex,
        ex.PaymentConfirmed(payment_id="pay-6", order_id="ord-6", amount=50.0),
        ex.OrderFulfillmentTimedOut(
            order_id="ord-6", stalled_status="awaiting_shipment"
        ),
    )

    last = transitions(ex, "ord-6")[-1]
    assert last.state["status"] == "cancelled"
    assert last.is_complete is True
    # No shipment_id was recorded, so no CancelShipment.
    assert issued_commands(ex, "ord-6")[3:] == [
        "RefundPayment",
        "ReleaseInventory",
        "CancelOrder",
    ]


def test_an_event_before_the_start_event_is_skipped_and_not_replayed(example):
    ex = example
    deliver(ex, ex.PaymentConfirmed(payment_id="pay-7", order_id="ord-7", amount=50.0))
    assert transitions(ex, "ord-7") == []

    deliver(ex, ex.OrderPlaced(order_id="ord-7", customer_id="c-1", total=50.0))

    [step] = transitions(ex, "ord-7")
    assert step.state["status"] == "awaiting_inventory"
    assert step.state["payment_id"] is None


def test_a_late_payment_failure_leaves_the_process_running(example):
    ex = example
    start_and_reserve(ex, "ord-8")
    deliver(
        ex,
        ex.PaymentConfirmed(payment_id="pay-8", order_id="ord-8", amount=50.0),
        ex.PaymentFailed(payment_id="pay-8", order_id="ord-8", reason="late"),
    )

    last = transitions(ex, "ord-8")[-1]
    assert last.handler_name == "on_payment_failed"
    assert last.state["status"] == "awaiting_shipment"
    assert last.is_complete is False
    assert "CancelOrder" not in issued_commands(ex, "ord-8")
