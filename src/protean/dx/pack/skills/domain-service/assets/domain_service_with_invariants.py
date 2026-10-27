"""
Domain service with comprehensive pre and post invariants.

This example demonstrates:
- Multiple @invariant.pre decorators for precondition validation
- Multiple @invariant.post decorators for postcondition validation
- Cross-aggregate validation spanning Order and Inventory, changing only
  the order. The inventory reserves stock later, from the OrderConfirmed
  event's items (see the add-domain-service-flow skill)
- Error collection from multiple invariant failures
- Callable class pattern combined with invariants

Usage:
    service = OrderPlacementService(order, inventories)
    service()  # Runs pre invariants -> __call__ -> post invariants
"""

from datetime import UTC, datetime
from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    DateTime,
    Decimal,
    Dict,
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

    def quantities_by_product(self) -> dict[str, int]:
        """Total quantity per product, adding up lines for the same product."""
        totals: dict[str, int] = {}
        for item in self.items:
            totals[item.product_id] = totals.get(item.product_id, 0) + item.quantity
        return totals

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
    price: Decimal(precision=19, scale=4)


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
class OrderPlacementService:
    """Domain service with pre and post invariants for order placement.

    Pre invariants validate:
    - Sufficient inventory stock
    - Valid payment method on the order

    Post invariants validate:
    - The order is confirmed
    - The OrderConfirmed event lists every ordered item and its quantity

    The service reads the inventory and changes only the order.
    """

    def __init__(self, order, inventories):
        super().__init__(order, inventories)

        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        # Two lines for the same product draw on the same stock, so check
        # their total.
        for product_id, quantity in self.order.quantities_by_product().items():
            inventory = next(
                (i for i in self.inventories if i.product_id == product_id), None
            )
            if inventory is None or inventory.quantity < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    @invariant.pre
    def order_payment_method_should_be_valid(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )

    @invariant.post
    def order_should_be_confirmed(self):
        if self.order.status != OrderStatus.CONFIRMED.value:
            raise ValidationError({"_service": ["Order was not confirmed"]})

    @invariant.post
    def confirmation_should_list_every_ordered_item(self):
        # The inventory reserves stock from the event's items, so an item
        # missing from the event would never be reserved.
        confirmations = [e for e in self.order._events if isinstance(e, OrderConfirmed)]
        ordered = self.order.quantities_by_product()
        listed: dict[str, int] = {}
        for line in confirmations[-1].items if confirmations else []:
            listed[line["product_id"]] = (
                listed.get(line["product_id"], 0) + line["quantity"]
            )

        if listed != ordered:
            raise ValidationError(
                {"_service": ["The confirmation does not list every ordered item"]}
            )

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

        # Callable with invariants: pre checks -> __call__ -> post checks
        OrderPlacementService(order, [inventory1, inventory2])()

        # The service changed only the order. The inventory is unchanged
        # until its own command handler reserves the stock.
        print(f"Order status: {order.status}")
        print(f"Items to reserve: {order._events[-1].items}")
        print(f"Inventory 1 quantity: {inventory1.quantity}")
        print(f"Inventory 2 quantity: {inventory2.quantity}")
