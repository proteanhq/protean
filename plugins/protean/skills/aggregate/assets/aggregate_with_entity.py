"""
Aggregate containing entities via HasOne and HasMany relationships.

This example demonstrates:
- Aggregate with enclosed entities
- HasOne relationship (one-to-one)
- HasMany relationship (one-to-many)
- Entity definition with part_of parameter
- Bidirectional references (automatic)
- Adding/removing entities

Usage:
    order = Order(customer_id="C123")
    order.add_line_items(LineItem(product_id="P1", quantity=2, unit_price=50.0))
    domain.repository_for(Order).add(order)
"""

from protean import Domain
from protean.fields import Float, HasMany, HasOne, Integer, Reference, String

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """An order aggregate that contains line items and shipping info."""

    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")

    # One-to-many relationship: an order has many line items
    line_items = HasMany("LineItem")

    # One-to-one relationship: an order has one shipping info
    shipping_info = HasOne("ShippingInfo")

    @property
    def total_amount(self) -> float:
        """Calculate total amount from all line items."""
        if not self.line_items:
            return 0.0
        return sum(item.subtotal for item in self.line_items)

    def place_order(self):
        """Place the order if it has items."""
        if not self.line_items:
            raise ValueError("Cannot place an order without line items")
        self.status = "placed"


@domain.entity(part_of="Order")
class LineItem:
    """A line item entity that belongs to an order."""

    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True)

    # Bidirectional reference back to parent (automatically created)
    order = Reference(Order)

    @property
    def subtotal(self) -> float:
        """Calculate subtotal for this line item."""
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ShippingInfo:
    """Shipping information entity for an order."""

    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
    postal_code: String(required=True, max_length=20)
    country: String(max_length=50, default="USA")

    # Bidirectional reference back to parent
    order = Reference(Order)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an order with line items
        order = Order(customer_id="CUST-12345")

        # Add line items
        item1 = LineItem(product_id="PROD-001", quantity=2, unit_price=29.99)
        item2 = LineItem(product_id="PROD-002", quantity=1, unit_price=49.99)
        order.add_line_items([item1, item2])

        # Add shipping info
        shipping = ShippingInfo(
            address="123 Main St",
            city="San Francisco",
            postal_code="94102",
            country="USA",
        )
        order.shipping_info = shipping

        print(f"Order ID: {order.id}")
        print(f"Customer: {order.customer_id}")
        print(f"Line items: {len(order.line_items)}")
        print(f"Total amount: ${order.total_amount:.2f}")
        print(f"Shipping to: {order.shipping_info.city}, {order.shipping_info.country}")

        # Access parent from child (bidirectional)
        print(f"First item's order ID: {item1.order_id}")

        # Place the order
        order.place_order()
        print(f"Order status: {order.status}")
