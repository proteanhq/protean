"""
Event-sourced aggregate with enclosed entities and value objects.

This example demonstrates:
- ES aggregate with HasMany entity relationships
- Events that capture entity-level changes
- @apply methods managing entity collections during replay
- Value objects within ES aggregates
- Factory classmethod with initial entities
- State reconstruction including entity relationships

Domain: Order with line items
    - Orders are created with initial items
    - Items can be added or removed
    - Orders can be confirmed (with validation)

Usage:
    from es_aggregate_with_entities import Order, domain

    domain.init(traverse=False)
    with domain.domain_context():
        order = Order.create(
            order_id="ORD-001",
            customer_id="CUST-123",
            items=[{"product_id": "P1", "description": "Widget", "quantity": 2, "unit_price": 25.0}],
        )
"""

import uuid

from protean import Domain
from protean.core.aggregate import apply
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
)

# Domain setup
domain = Domain()


# --- Value Object ---


@domain.value_object
class Money:
    """Immutable monetary amount."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")


# --- Entity ---


@domain.entity(part_of="Order")
class LineItem:
    """A line item within an order."""

    item_id: Identifier(identifier=True)
    product_id: String(required=True, max_length=50)
    description: String(max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price


# --- Events ---


@domain.event(part_of="Order")
class OrderCreated:
    """Raised when a new order is created."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)


@domain.event(part_of="Order")
class ItemAdded:
    """Raised when an item is added to the order."""

    order_id: Identifier(required=True)
    item_id: Identifier(required=True)
    product_id: String(required=True)
    description: String()
    quantity: Integer(required=True)
    unit_price: Float(required=True)


@domain.event(part_of="Order")
class ItemRemoved:
    """Raised when an item is removed from the order."""

    order_id: Identifier(required=True)
    item_id: Identifier(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    """Raised when the order is confirmed for processing."""

    order_id: Identifier(required=True)


# --- Aggregate ---


@domain.aggregate(event_sourced=True)
class Order:
    """Event-sourced order aggregate with line items.

    Demonstrates ES aggregate with HasMany entity relationships.
    Business methods validate and raise events via raise_().
    @apply methods handle all state mutations (called automatically by raise_()).
    """

    order_id: Identifier(identifier=True)
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="DRAFT")
    items: HasMany(LineItem)

    @property
    def total(self) -> float:
        """Calculate order total from line items."""
        return sum(item.subtotal for item in self.items)

    # --- Factory classmethod ---

    @classmethod
    def create(cls, order_id, customer_id, items=None):
        """Create a new order and optionally add initial items."""
        order = cls(order_id=order_id, customer_id=customer_id)
        order.raise_(OrderCreated(order_id=order_id, customer_id=customer_id))

        # Add initial items if provided
        if items:
            for item_data in items:
                order.add_item(**item_data)

        return order

    # --- Business methods (validate then raise; @apply handles state) ---

    def add_item(self, product_id, description="", quantity=1, unit_price=0.0):
        """Add an item to the order."""
        if self.status != "DRAFT":
            raise ValueError(f"Cannot add items to order in '{self.status}' status")

        item_id = str(uuid.uuid4())
        self.raise_(
            ItemAdded(
                order_id=self.order_id,
                item_id=item_id,
                product_id=product_id,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
            )
        )

    def remove_item(self, item_id):
        """Remove an item from the order."""
        if self.status != "DRAFT":
            raise ValueError(
                f"Cannot remove items from order in '{self.status}' status"
            )

        existing = [item for item in self.items if item.item_id == item_id]
        if not existing:
            raise ValueError(f"Item {item_id} not found in order")

        self.raise_(ItemRemoved(order_id=self.order_id, item_id=item_id))

    def confirm(self):
        """Confirm the order for processing."""
        if self.status != "DRAFT":
            raise ValueError(f"Cannot confirm order in '{self.status}' status")
        if not self.items:
            raise ValueError("Cannot confirm order with no items")
        self.raise_(OrderConfirmed(order_id=self.order_id))

    # --- @apply methods (for replaying events during state reconstruction) ---

    @apply
    def order_created(self, event: OrderCreated):
        self.order_id = event.order_id
        self.customer_id = event.customer_id
        self.status = "DRAFT"

    @apply
    def item_added(self, event: ItemAdded):
        item = LineItem(
            item_id=event.item_id,
            product_id=event.product_id,
            description=event.description,
            quantity=event.quantity,
            unit_price=event.unit_price,
        )
        self.add_items(item)

    @apply
    def item_removed(self, event: ItemRemoved):
        existing = [item for item in self.items if item.item_id == event.item_id]
        if existing:
            self.remove_items(existing[0])

    @apply
    def order_confirmed(self, event: OrderConfirmed):
        self.status = "CONFIRMED"


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        order = Order.create(
            order_id="ORD-001",
            customer_id="CUST-123",
            items=[
                {
                    "product_id": "PROD-A",
                    "description": "Widget",
                    "quantity": 2,
                    "unit_price": 25.00,
                },
                {
                    "product_id": "PROD-B",
                    "description": "Gadget",
                    "quantity": 1,
                    "unit_price": 75.00,
                },
            ],
        )

        print(
            f"Order {order.order_id}: {len(order.items)} items, total=${order.total:.2f}"
        )
        print(f"Status: {order.status}")
        print(f"Events: {len(order._events)}")

        order.confirm()
        print(f"After confirm: status={order.status}")
