from fulfillment import (
    InventoryReserved,
    Order,
    OrderCancelled,
    OrderItem,
    OrderPlaced,
    PlaceOrder,
    Reservation,
    domain,
)


# --8<-- [start:get_order]
def get_order(order_id):
    return domain.repository_for(Order).get(order_id)


# --8<-- [end:get_order]


# --8<-- [start:engine_test_mode]
from protean.server import Engine


def test_order_creates_inventory_reservation():
    """Test that creating an order reserves inventory."""
    # Arrange: Create order (raises events)
    with domain.domain_context():
        order = Order.create(
            customer_id="123", items=[OrderItem(product_id="ABC", quantity=5)]
        )
        domain.repository_for(Order).add(order)

    # Act: Process events in test mode
    engine = Engine(domain, test_mode=True)
    engine.run()

    # Assert: Verify inventory was reserved
    with domain.domain_context():
        reservation = domain.repository_for(Reservation).get_by_order(order.id)
        assert reservation is not None
        assert reservation.quantity == 5


# --8<-- [end:engine_test_mode]


# --8<-- [start:cascade]
def test_order_fulfillment_flow():
    """Test complete order fulfillment flow."""
    # Order created -> Inventory reserved -> Order shipped
    with domain.domain_context():
        order = Order.create(
            customer_id="123", items=[OrderItem(product_id="ABC", quantity=5)]
        )
        domain.repository_for(Order).add(order)

    # Process all cascading events
    engine = Engine(domain, test_mode=True)
    engine.run()

    with domain.domain_context():
        order = domain.repository_for(Order).get(order.id)
        assert order.status == "shipped"


# --8<-- [end:cascade]


# --8<-- [start:process_and_wait]
from protean.testing import process_and_wait


def test_placing_an_order_reserves_inventory():
    outcome = process_and_wait(
        PlaceOrder(order_id="o1", product_id="ABC", qty=5), domain
    )

    assert outcome.succeeded
    assert OrderPlaced in outcome.events
    assert outcome.events[OrderPlaced].order_id == "o1"

    with domain.domain_context():
        reservation = domain.repository_for(Reservation).get("o1")
        assert reservation.quantity == 5


# --8<-- [end:process_and_wait]


# --8<-- [start:event_log]
def test_the_event_log():
    outcome = process_and_wait(
        PlaceOrder(order_id="o1", product_id="ABC", qty=5), domain
    )

    assert OrderPlaced in outcome.events  # membership by type
    assert outcome.events[OrderPlaced].order_id == "o1"  # first event of a type
    assert outcome.events.get(OrderCancelled) is None  # safe access, no KeyError
    assert outcome.events.types == [OrderPlaced, InventoryReserved]
    assert len(outcome.events) == 2


# --8<-- [end:event_log]


# --8<-- [start:drain]
from protean.testing import drain


def test_order_ships_after_reservation():
    domain.process(PlaceOrder(order_id="o1", product_id="ABC", qty=5))

    drain(domain, until=lambda: get_order("o1").status == "shipped")

    assert get_order("o1").status == "shipped"


# --8<-- [end:drain]
