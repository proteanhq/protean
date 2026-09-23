"""
Domain service with comprehensive pre and post invariants.

This example demonstrates:
- Multiple @invariant.pre decorators for precondition validation
- Multiple @invariant.post decorators for postcondition validation
- Cross-aggregate validation spanning Order and Inventory
- Error collection from multiple invariant failures
- Callable class pattern combined with invariants

Usage:
    service = OrderPlacementService(order, inventories)
    service()  # Runs pre invariants -> __call__ -> post invariants
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
class OrderPlacementService:
    """Domain service with pre and post invariants for order placement.

    Pre invariants validate:
    - Sufficient inventory stock
    - Valid payment method on the order

    Post invariants validate:
    - Reserved value matches order value
    - Reserved quantity matches order quantity
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

    @invariant.pre
    def order_payment_method_should_be_valid(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )

    @invariant.post
    def total_reserved_value_should_match_order_value(self):
        order_total = sum(item.quantity * item.price for item in self.order.items)
        reserved_total = 0
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory:
                reserved_total += inventory._events[0].quantity * item.price

        if order_total != reserved_total:
            raise ValidationError(
                {"_service": ["Total reserved value does not match order value"]}
            )

    @invariant.post
    def total_quantity_reserved_should_match_order_quantity(self):
        order_quantity = sum(item.quantity for item in self.order.items)
        reserved_quantity = sum(
            inventory._events[0].quantity
            for inventory in self.inventories
            if inventory._events
        )

        if order_quantity != reserved_quantity:
            raise ValidationError(
                {"_service": ["Total reserved quantity does not match order quantity"]}
            )

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

        # Callable with invariants: pre checks -> __call__ -> post checks
        OrderPlacementService(order, [inventory1, inventory2])()

        print(f"Order status: {order.status}")
        print(f"Inventory 1 remaining: {inventory1.quantity}")
        print(f"Inventory 2 remaining: {inventory2.quantity}")
