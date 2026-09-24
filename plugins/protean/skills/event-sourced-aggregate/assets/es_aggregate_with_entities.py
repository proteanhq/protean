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

from protean import Domain, invariant
from protean.core.aggregate import apply
from protean.exceptions import ValidationError
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

# Domain setup
domain = Domain()

# The smallest price a sold item may carry. Written once and applied twice: on
# the event, so an invalid ItemAdded cannot be built, and on the entity, so an
# item assembled any other way is rejected too.
MINIMUM_UNIT_PRICE = 0.01


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
    unit_price: ValueObject(Money, required=True)

    @invariant.post
    def price_must_be_positive(self):
        """`min_value` cannot reach inside an embedded value object, so the
        rule that a sold item costs something lives here."""
        if self.unit_price.amount < MINIMUM_UNIT_PRICE:
            raise ValidationError(
                {"unit_price": [f"Unit price must be at least {MINIMUM_UNIT_PRICE}"]}
            )

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price.amount


# --- Events ---


@domain.event(part_of="Order")
class OrderCreated:
    """Raised when a new order is created."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    currency: String(max_length=3, default="USD")


@domain.event(part_of="Order")
class ItemAdded:
    """Raised when an item is added to the order.

    The event carries the same constraints as the `LineItem` it describes.
    `raise_()` appends the event and then runs the apply handler, so a
    constraint that lives only on the entity is checked after the event is
    already pending: the caller sees the error, and a rejected event sits in
    `_events` waiting to be saved. Declaring the constraints here means an
    invalid `ItemAdded` cannot be built at all, so `raise_()` is never reached.
    """

    order_id: Identifier(required=True)
    item_id: Identifier(required=True)
    product_id: String(required=True, max_length=50)
    description: String(max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=MINIMUM_UNIT_PRICE)


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
    currency: String(max_length=3, default="USD")
    items: HasMany(LineItem)

    @property
    def total(self) -> Money:
        """Order total. Every item is priced in the order's currency, so the
        amounts can be summed."""
        return Money(
            amount=sum(item.subtotal for item in self.items),
            currency=self.currency,
        )

    @invariant.post
    def items_share_the_order_currency(self):
        """A safety net for an order built by hand rather than from events.

        Note what this invariant cannot do: `from_events()` suppresses
        invariant checks for the whole replay, so it never runs there. That is
        why the currency lives on the order and `ItemAdded` does not carry one.
        A stream cannot describe a mixed order, so replay cannot build one.
        """
        mismatched = {
            item.unit_price.currency
            for item in self.items
            if item.unit_price.currency != self.currency
        }
        if mismatched:
            raise ValidationError(
                {
                    "items": [
                        f"Order is in {self.currency}; items priced in "
                        f"{sorted(mismatched)}"
                    ]
                }
            )

    # --- Factory classmethod ---

    @classmethod
    def create(cls, order_id, customer_id, currency="USD", items=None):
        """Create a new order and optionally add initial items."""
        order = cls(order_id=order_id, customer_id=customer_id, currency=currency)
        order.raise_(
            OrderCreated(
                order_id=order_id, customer_id=customer_id, currency=currency
            )
        )

        # Add initial items if provided
        if items:
            for item_data in items:
                order.add_item(**item_data)

        return order

    # --- Business methods (validate then raise; @apply handles state) ---

    def add_item(self, product_id, unit_price, description="", quantity=1):
        """Add an item to the order. Items are priced in the order's currency."""
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
        self.currency = event.currency
        self.status = "DRAFT"

    @apply
    def item_added(self, event: ItemAdded):
        item = LineItem(
            item_id=event.item_id,
            product_id=event.product_id,
            description=event.description,
            quantity=event.quantity,
            unit_price=Money(amount=event.unit_price, currency=self.currency),
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
            f"Order {order.order_id}: {len(order.items)} items, "
            f"total={order.total.amount:.2f} {order.total.currency}"
        )
        print(f"Status: {order.status}")
        print(f"Events: {len(order._events)}")

        order.confirm()
        print(f"After confirm: status={order.status}")
