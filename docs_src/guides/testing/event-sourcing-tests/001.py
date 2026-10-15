from uuid import uuid4

from ordering_es import (
    ConfirmOrder,
    CreateOrder,
    InitiatePayment,
    Order,
    OrderConfirmed,
    OrderCreated,
    PaymentFailed,
    PaymentPending,
)

# --8<-- [start:three_words]
from protean.testing import given


def test_given_after_process(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"


# --8<-- [end:three_words]


# --8<-- [start:chaining]
def test_multi_command_chaining():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"


# --8<-- [end:chaining]


# --8<-- [start:events_vs_all_events]
def test_events_hold_only_the_last_command():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
    )

    # .events has only the last command's events
    assert OrderConfirmed in order.events
    assert OrderCreated not in order.events

    # .all_events has everything
    assert order.all_events.types == [OrderCreated, OrderConfirmed]


# --8<-- [end:events_vs_all_events]


# --8<-- [start:aggregate_state]
def test_aggregate_state(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert order.status == "PAYMENT_PENDING"
    assert order.customer == "Alice"
    assert order.pricing.grand_total == 99.99  # deep access works
    assert isinstance(order.aggregate, Order)  # the raw aggregate


# --8<-- [end:aggregate_state]


# --8<-- [start:accepted_or_rejected]
def test_accepted_command(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert order.accepted  # command processed without exception
    assert not order.rejected  # command raised no exception
    assert order.rejection is None  # the exception object, or None
    assert order.rejection_messages == []  # error strings, empty when accepted


# --8<-- [end:accepted_or_rejected]


# --8<-- [start:rejection_messages]
def test_rejection_messages(order_created, initiate_payment):
    order = given(Order, order_created).process(initiate_payment)

    assert order.rejected
    assert "Order must be confirmed before payment" in order.rejection_messages


# --8<-- [end:rejection_messages]


# --8<-- [start:event_log]
def test_event_log(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    # Presence check
    assert PaymentPending in order.events

    # Truthiness: truthy when non-empty, falsy when empty
    assert order.events

    # Access by type (first match; raises KeyError if missing)
    assert order.events[PaymentPending].payment_id == "pay-001"

    # Safe access (returns None if missing)
    assert order.events.get(PaymentFailed) is None

    # First and last event
    assert order.events.first is order.events[0]
    assert order.events.last is order.events[-1]

    # Ordered type list
    assert order.events.types == [PaymentPending]

    # Count
    assert len(order.events) == 1

    # All events of a type
    assert len(order.events.of_type(PaymentPending)) == 1

    # Iteration
    for event in order.events:
        print(event)

    # Access by index
    assert order.events[0].payment_id == "pay-001"


# --8<-- [end:event_log]


# --8<-- [start:raw_aggregate]
def test_raw_aggregate(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert isinstance(order.aggregate, Order)


# --8<-- [end:raw_aggregate]


# --8<-- [start:create_command]
def test_create_order():
    order = given(Order).process(
        CreateOrder(order_id="ord-1", customer="Alice", amount=99.99)
    )

    assert order.accepted
    assert OrderCreated in order.events
    assert order.status == "CREATED"
    assert order.customer == "Alice"


# --8<-- [end:create_command]


# --8<-- [start:command_with_history]
def test_confirm_order(order_created):
    order = given(Order, order_created).process(
        ConfirmOrder(order_id=order_created.order_id)
    )

    assert order.accepted
    assert OrderConfirmed in order.events
    assert order.status == "CONFIRMED"


# --8<-- [end:command_with_history]


# --8<-- [start:rejection]
def test_cannot_pay_unconfirmed_order(order_created, initiate_payment):
    order = given(Order, order_created).process(initiate_payment)

    assert order.rejected
    assert "Order must be confirmed before payment" in order.rejection_messages
    assert not order.events
    assert order.status == "CREATED"  # unchanged


# --8<-- [end:rejection]


# --8<-- [start:multiple_history]
def test_payment_on_confirmed_order(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created).after(order_confirmed).process(initiate_payment)

    assert order.accepted
    assert PaymentPending in order.events
    assert order.events[PaymentPending].payment_id == "pay-001"


# --8<-- [end:multiple_history]


# --8<-- [start:event_attributes]
def test_payment_event_carries_payment_id(order_created, order_confirmed):
    order = given(Order, order_created, order_confirmed).process(
        InitiatePayment(order_id=order_created.order_id, payment_id="pay-42")
    )

    event = order.events[PaymentPending]
    assert event.payment_id == "pay-42"
    assert event.order_id == order_created.order_id


# --8<-- [end:event_attributes]


# --8<-- [start:lifecycle]
def test_order_lifecycle():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"
    assert order.all_events.types == [OrderCreated, OrderConfirmed, PaymentPending]


# --8<-- [end:lifecycle]


# --8<-- [start:rejection_mid_chain]
def test_cannot_pay_without_confirming():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.rejected
    assert "Order must be confirmed before payment" in order.rejection_messages
    assert order.status == "CREATED"  # reflects state after CreateOrder


# --8<-- [end:rejection_mid_chain]


# The `.after()` signature block on the page chains from an empty `given()`.
def test_after_accumulates_history(order_created, order_confirmed, initiate_payment):
    order = (
        given(Order)
        .after(order_created)
        .after(order_confirmed)
        .process(initiate_payment)
    )

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"
