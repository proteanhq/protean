"""
Entity with HasOne relationship (one-to-one).

This example demonstrates:
- Entity with HasOne association to another entity
- One-to-one relationship between entities
- Nested entity structure within aggregate
- Setting and accessing HasOne relationships
- Validation and business logic in entities

Usage:
    order = Order(customer_id="C123")
    shipping = ShippingInfo(address="123 Main St", city="NYC")
    order.shipping_info = shipping
    domain.repository_for(Order).add(order)
"""

from protean import Domain
from protean.fields import Float, HasMany, HasOne, Integer, Reference, String

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """An order aggregate containing line items and shipping info."""

    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="pending")

    # One-to-many: order has many line items
    line_items = HasMany("LineItem")

    # One-to-one: order has one shipping info
    shipping_info = HasOne("ShippingInfo")

    @property
    def total_amount(self) -> float:
        """Calculate total order amount."""
        if not self.line_items:
            return 0.0
        return sum(item.subtotal for item in self.line_items)

    @property
    def is_shippable(self) -> bool:
        """Check if order can be shipped."""
        return self.shipping_info is not None and len(self.line_items) > 0

    def validate_for_shipment(self):
        """Validate order is ready for shipment."""
        if not self.line_items:
            raise ValueError("Order must have at least one line item")
        if self.shipping_info is None:
            raise ValueError("Order must have shipping information")
        if not self.shipping_info.is_valid:
            raise ValueError("Shipping address is incomplete")

    def ship(self):
        """Mark order as shipped."""
        self.validate_for_shipment()
        self.status = "shipped"


@domain.entity(part_of="Order")
class LineItem:
    """A line item entity in an order."""

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)

    # Reference back to parent aggregate (automatic)
    order = Reference("Order")

    @property
    def subtotal(self) -> float:
        """Calculate line item subtotal."""
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ShippingInfo:
    """Shipping information entity for an order."""

    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(max_length=50, default="USA")
    phone: String(max_length=20)

    # Reference back to parent aggregate (automatic)
    order = Reference("Order")

    @property
    def is_valid(self) -> bool:
        """Check if shipping information is complete."""
        return all(
            [
                self.address,
                self.city,
                self.postal_code,
                self.country,
            ]
        )

    @property
    def full_address(self) -> str:
        """Get formatted full address."""
        parts = [self.address, self.city]
        if self.state:
            parts.append(self.state)
        parts.extend([self.postal_code, self.country])
        return ", ".join(parts)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an order
        order = Order(customer_id="CUST-12345")

        # Add line items
        item1 = LineItem(
            product_id="PROD-001",
            product_name="Laptop",
            quantity=1,
            unit_price=999.99,
        )
        item2 = LineItem(
            product_id="PROD-002",
            product_name="Mouse",
            quantity=2,
            unit_price=29.99,
        )
        order.add_line_items([item1, item2])

        # Create and set shipping info (HasOne relationship)
        shipping = ShippingInfo(
            address="123 Main Street",
            city="San Francisco",
            state="CA",
            postal_code="94102",
            country="USA",
            phone="+1-555-0123",
        )
        order.shipping_info = shipping

        print(f"Order ID: {order.id}")
        print(f"Customer: {order.customer_id}")
        print(f"Line items: {len(order.line_items)}")
        print(f"Total: ${order.total_amount:.2f}")

        # Access HasOne relationship
        print("\nShipping to:")
        print(f"  {order.shipping_info.full_address}")
        print(f"  Phone: {order.shipping_info.phone}")
        print(f"  Valid: {order.shipping_info.is_valid}")

        # Check if shippable
        print(f"\nIs shippable: {order.is_shippable}")

        # Ship the order
        order.ship()
        print(f"Order status: {order.status}")

        # Demonstrate bidirectional reference
        print(f"\nShipping info's order ID: {shipping.order_id}")
