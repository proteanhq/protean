"""
Domain service with class methods for stateless operations.

This example demonstrates:
- Domain service using @classmethod for a functional style
- No __init__ required - aggregates passed directly to methods
- Inline validation (no @invariant support with class methods)
- Explicit return of modified aggregates
- Direct class method invocation without instantiation

Usage:
    order, inventories = OrderPlacementService.place_order(order, [inventory])
"""

from datetime import UTC, datetime
from enum import Enum

from protean import Domain
from protean.fields import (
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
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
    order_id: Identifier(required=True)
    confirmed_at: DateTime(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id: Identifier()

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(OrderConfirmed(order_id=self.id, confirmed_at=datetime.now(UTC)))


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

    def reserve_stock(self, quantity: int):
        self.quantity -= quantity
        self.raise_(
            StockReserved(
                product_id=self.product_id,
                quantity=quantity,
                reserved_at=datetime.now(UTC),
            )
        )


@domain.domain_service(part_of=["Order", "Inventory"])
class OrderPlacementService:
    """Domain service with class methods for order placement.

    Call directly without instantiation:
        order, inventories = OrderPlacementService.place_order(order, [inventory])
    """

    @classmethod
    def place_order(cls, order: Order, inventories: list[Inventory]):
        """Place the order and reserve inventory stock.

        Validates stock availability inline, then mutates aggregates.
        Returns the modified aggregates.
        """
        for item in order.items:
            inventory = next(
                (i for i in inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise Exception("Product is out of stock")

            inventory.reserve_stock(item.quantity)

        order.confirm()

        return order, inventories


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

        # Class method pattern: call directly without instantiation
        order, inventories = OrderPlacementService.place_order(
            order, [inventory1, inventory2]
        )

        print(f"Order status: {order.status}")
        print(f"Inventory 1 remaining: {inventory1.quantity}")
        print(f"Inventory 2 remaining: {inventory2.quantity}")
