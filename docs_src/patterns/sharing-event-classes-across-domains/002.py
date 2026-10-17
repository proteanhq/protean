from protean import Domain
from protean.fields import Float, HasMany, Identifier, Integer, List, String

domain = Domain(name="Ordering")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(required=True)
    quantity: Integer(min_value=1, required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    total: Float(default=0.0)

    def place(self):
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
                total=self.total,
            )
        )


# --8<-- [start:publisher_test]
class TestOrderPlacedContract:
    """Verify that OrderPlaced events conform to the published schema."""

    def test_order_placed_has_required_fields(self, test_domain):
        order = Order(
            customer_id="cust-123",
            total=100.0,
        )
        order.add_items(OrderItem(product_id="prod-1", quantity=2))
        order.place()

        event = order._events[0]
        event_dict = event.to_dict()

        # Verify contract fields exist and have correct types
        assert "order_id" in event_dict
        assert isinstance(event_dict["order_id"], str)
        assert "customer_id" in event_dict
        assert isinstance(event_dict["customer_id"], str)
        assert "items" in event_dict
        assert isinstance(event_dict["items"], list)
        assert "total" in event_dict
        assert isinstance(event_dict["total"], (int, float))


# --8<-- [end:publisher_test]
