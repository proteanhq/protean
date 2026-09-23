"""
Domain service as a callable class with a single business operation.

This example demonstrates:
- Callable domain service using __call__ method
- Association with two aggregates via part_of
- Pre invariant for cross-aggregate validation
- Aggregate mutation across Order and Inventory aggregates
- Event raising from aggregate methods during service execution

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
from protean.core.domain_service import BaseDomainService
from protean.exceptions import ValidationError
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
class place_order:
    """Callable domain service that places an order and reserves inventory.

    Instantiate with aggregates and call to execute:
        place_order(order, [inventory])()
    """

    def __init__(self, order, inventories):
        # Note: Use explicit base class call instead of super() because the
        # @domain.domain_service decorator replaces the class via derive_element_class,
        # which breaks super()'s __class__ cell reference.
        BaseDomainService.__init__(self, *(order, inventories))

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
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)

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

        print(f"Order status: {order.status}")
        print(f"Inventory 1 remaining: {inventory1.quantity}")
        print(f"Inventory 2 remaining: {inventory2.quantity}")
