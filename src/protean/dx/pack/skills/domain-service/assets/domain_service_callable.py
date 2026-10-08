"""
Domain service as a callable class with a single business operation.

This example demonstrates:
- Callable domain service using __call__ method
- Association with two aggregates via part_of
- Pre invariant for cross-aggregate validation
- Reading the inventory to validate, and changing only the order
- An OrderConfirmed event that carries the items, so the inventory can
  reserve stock later through an event handler and a command (see the
  add-domain-service-flow skill)

Usage:
    order = Order(customer_id="CUST-001", payment_id="PAY-001")
    order.add_items(OrderItem(product_id="PROD-001", quantity=2, price=29.99))
    inventory = Inventory(product_id="PROD-001", quantity=100,
                          warehouse=Warehouse(location="NYC", contact="John"))
    place_order(order, [inventory])()
"""

from datetime import UTC, datetime
from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    DateTime,
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)

domain = Domain()


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.event(part_of="Order")
class OrderConfirmed:
    """Carries the items, so the inventory side can reserve stock for them."""

    order_id: Identifier(required=True)
    items = List(content_type=Dict)
    confirmed_at: DateTime(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id: Identifier()

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
                confirmed_at=datetime.now(UTC),
            )
        )


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer()
    price: Float()


@domain.value_object(part_of="Inventory")
class Warehouse:
    location: String()
    contact: String()


@domain.event(part_of="Inventory")
class StockReserved:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    reserved_at: DateTime(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    quantity: Integer()
    warehouse = ValueObject(Warehouse)

    # The inventory's own command handler calls this, when an event handler
    # reacting to OrderConfirmed issues it a command. The domain service
    # never does.
    def reserve_stock(self, quantity: int):
        self.quantity -= quantity
        self.raise_(
            StockReserved(
                product_id=self.product_id,
                quantity=quantity,
                reserved_at=datetime.now(UTC),
            )
        )


@domain.domain_service(part_of=[Order, Inventory])
class place_order:
    """Callable domain service that checks stock and confirms the order.

    Instantiate with aggregates and call to execute:
        place_order(order, [inventory])()
    """

    def __init__(self, order, inventories):
        super().__init__(order, inventories)

        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    def __call__(self):
        self.order.confirm()


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        order = Order(
            customer_id="CUST-001",
            payment_id="PAY-001",
            items=[
                OrderItem(product_id="PROD-001", quantity=2, price=29.99),
                OrderItem(product_id="PROD-002", quantity=1, price=49.99),
            ],
        )

        inventory1 = Inventory(
            product_id="PROD-001",
            quantity=100,
            warehouse=Warehouse(location="NYC", contact="John Doe"),
        )
        inventory2 = Inventory(
            product_id="PROD-002",
            quantity=50,
            warehouse=Warehouse(location="LA", contact="Jane Smith"),
        )

        # Callable pattern: instantiate and call
        place_order(order, [inventory1, inventory2])()

        # The service changed only the order. The inventory is unchanged
        # until its own command handler reserves the stock.
        print(f"Order status: {order.status}")
        print(f"Items to reserve: {order._events[-1].items}")
        print(f"Inventory 1 quantity: {inventory1.quantity}")
        print(f"Inventory 2 quantity: {inventory2.quantity}")
