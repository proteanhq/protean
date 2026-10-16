# --8<-- [start:entities]
from isolation_shop.domain import Order


class TestOrderItems:
    def test_adding_items(self):
        order = Order(customer_id="cust-123")

        order.add_item(
            product_id="prod-1",
            product_name="Widget",
            quantity=2,
            unit_price=15.0,
        )

        assert len(order.items) == 1
        assert order.items[0].product_id == "prod-1"
        assert order.items[0].quantity == 2

    def test_removing_items(self):
        order = Order(customer_id="cust-123")
        order.add_item(
            product_id="prod-1",
            product_name="Widget",
            quantity=2,
            unit_price=15.0,
        )

        order.remove_item("prod-1")

        assert len(order.items) == 0

    def test_updating_item_quantity(self):
        order = Order(customer_id="cust-123")
        order.add_item(
            product_id="prod-1",
            product_name="Widget",
            quantity=2,
            unit_price=15.0,
        )

        order.update_item_quantity("prod-1", 5)

        assert order.items[0].quantity == 5


# --8<-- [end:entities]
