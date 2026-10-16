# --8<-- [start:level1]
from ecommerce.domain import Order, OrderPlaced


class TestOrderPlacement:
    """Level 1: Test aggregate behavior in isolation."""

    def test_placing_order_transitions_status(self):
        order = Order(
            customer_id="cust-123",
            product_id="prod-1",
            total=99.95,
        )

        order.place()

        assert order.status == "placed"

    def test_placing_order_raises_order_placed_event(self):
        order = Order(
            customer_id="cust-123",
            product_id="prod-1",
            total=99.95,
        )

        order.place()

        assert len(order._events) == 1
        event = order._events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == order.order_id
        assert event.customer_id == "cust-123"
        assert event.total == 99.95


# --8<-- [end:level1]
