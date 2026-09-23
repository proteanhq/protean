"""
Repository handling aggregates with child entities.

This example demonstrates:
- Repository automatically syncs child entities (HasMany, HasOne)
- Adding child entities to an aggregate and persisting via the aggregate's repository
- Children are persisted/removed automatically with the aggregate
- No need to create repositories for child entities
- Loading an aggregate retrieves all its children

Usage:
    repo = domain.repository_for(Order)
    order = Order(order_id="ORD-001", customer_id="CUST-123")
    order.add_item("PROD-1", 2, 10.0)
    repo.add(order)
"""

from protean import Domain
from protean.fields import (
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    Reference,
    String,
)

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate with enclosed child entities.

    Contains HasMany LineItems and HasOne ShippingAddress.
    The repository persists the entire aggregate including children.
    """

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    items = HasMany("LineItem")
    shipping_address = HasOne("ShippingAddress")

    @property
    def item_count(self) -> int:
        return len(self.items) if self.items else 0

    @property
    def total(self) -> float:
        if not self.items:
            return 0.0
        return sum(item.quantity * item.unit_price for item in self.items)

    def add_item(self, product_id: str, quantity: int, unit_price: float):
        """Add a line item to the order."""
        item = LineItem(
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.add_items([item])

    def place(self):
        """Place the order."""
        if not self.items:
            raise ValueError("Cannot place an empty order")
        if not self.shipping_address:
            raise ValueError("Shipping address is required")
        self.status = "placed"


@domain.entity(part_of="Order")
class LineItem:
    """Line item entity enclosed within Order aggregate."""

    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True)

    order = Reference(Order)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ShippingAddress:
    """Shipping address entity enclosed within Order aggregate."""

    street: String(required=True)
    city: String(required=True)
    zip_code: String(required=True)
    country: String(default="US")

    order = Reference(Order)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        repo = domain.repository_for(Order)

        # Create order with children
        order = Order(order_id="ORD-001", customer_id="CUST-123")

        # Add line items via helper method
        order.add_item("PROD-1", 2, 29.99)
        order.add_item("PROD-2", 1, 49.99)

        # Set shipping address
        order.shipping_address = ShippingAddress(
            street="123 Main St",
            city="Springfield",
            zip_code="62704",
        )

        # Persist aggregate — all children are saved automatically
        repo.add(order)
        print(
            f"Persisted order with {order.item_count} items, total=${order.total:.2f}"
        )

        # Load aggregate — children are loaded too
        loaded = repo.get("ORD-001")
        print(
            f"Loaded order: {loaded.item_count} items, address={loaded.shipping_address.city}"
        )
