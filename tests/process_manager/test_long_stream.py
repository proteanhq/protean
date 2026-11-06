"""A process manager loads every transition in its stream, past one read page.

The ``small_read_page`` fixture shrinks a read page to a few rows, so a short
stream stands in for one longer than the default 1,000.
"""

from uuid import uuid4

import pytest

from tests.conftest import SMALL_READ_PAGE

from .elements import (
    Order,
    OrderFulfillmentPM,
    OrderPlaced,
    Payment,
    PaymentConfirmed,
    PaymentFailed,
    ShipmentDelivered,
    Shipping,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Payment)
    test_domain.register(PaymentConfirmed, part_of=Payment)
    test_domain.register(PaymentFailed, part_of=Payment)
    test_domain.register(Shipping)
    test_domain.register(ShipmentDelivered, part_of=Shipping)
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)


# Two full pages, which ends the load on an empty read, and two full pages
# plus part of a third.
@pytest.fixture(params=[2 * SMALL_READ_PAGE, 2 * SMALL_READ_PAGE + 5])
def transitions(request):
    return request.param


@pytest.fixture
def order_id(small_read_page, transitions):
    """Write ``transitions`` transitions to one PM's stream and return its id.

    The first transition comes from a real start event; the rest are written
    straight to the stream, each with a new ``payment_id``, so the last one
    sets ``payment_id`` to ``pay-<transitions - 2>``.
    """
    order_id = str(uuid4())
    OrderFulfillmentPM._handle(
        OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
    )

    pm = OrderFulfillmentPM._load_or_create(order_id, is_start=False)
    pm.status = "awaiting_shipment"
    for i in range(transitions - 1):
        pm.payment_id = f"pay-{i}"
        OrderFulfillmentPM._persist_transition(pm, "on_payment_confirmed")

    return order_id


def _stream(order_id):
    return f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"


@pytest.mark.eventstore
def test_load_applies_the_last_transition(test_domain, order_id, transitions):
    assert len(list(test_domain.event_store.store.read_all(_stream(order_id)))) == (
        transitions
    )

    pm = OrderFulfillmentPM._load_or_create(order_id, is_start=False)

    assert pm.payment_id == f"pay-{transitions - 2}"
    assert pm.status == "awaiting_shipment"
    assert pm._version == transitions - 1


@pytest.mark.eventstore
def test_next_transition_persists_past_one_page(test_domain, order_id, transitions):
    OrderFulfillmentPM._handle(ShipmentDelivered(order_id=order_id))

    messages = list(test_domain.event_store.store.read_all(_stream(order_id)))
    assert len(messages) == transitions + 1
    assert messages[-1].metadata.event_store.position == transitions

    pm = OrderFulfillmentPM._load_or_create(order_id, is_start=False)
    assert pm.status == "completed"
    assert pm.payment_id == f"pay-{transitions - 2}"
    assert pm._is_complete
