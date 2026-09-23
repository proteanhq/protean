"""
Aggregate using value objects for complex data types.

This example demonstrates:
- Value object definition
- ValueObject field in aggregate
- Value object with behavior (methods)
- Value object immutability
- Value objects in entities

Usage:
    money = Money(amount=100, currency="USD")
    order = Order(customer_id="C123", total=money)
"""

from protean import Domain
from protean.fields import Float, HasMany, Integer, String, ValueObject

# Domain setup
domain = Domain()


@domain.value_object
class Money:
    """Value object representing monetary amounts."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        """Add two money values (must be same currency)."""
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def multiply(self, factor: float) -> "Money":
        """Multiply money by a factor."""
        return Money(amount=self.amount * factor, currency=self.currency)

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"


@domain.value_object
class Address:
    """Value object representing a physical address."""

    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(max_length=50, default="USA")

    def full_address(self) -> str:
        """Return full formatted address."""
        parts = [self.street, self.city]
        if self.state:
            parts.append(self.state)
        parts.extend([self.postal_code, self.country])
        return ", ".join(parts)


@domain.entity(part_of="Order")
class OrderLine:
    """Order line with money value object for pricing."""

    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        """Calculate line total."""
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    """Order aggregate using value objects for money and address."""

    customer_id: String(required=True, max_length=50)

    # Value objects directly in aggregate
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)

    # Entities containing value objects
    lines = HasMany("OrderLine")

    @property
    def order_total(self) -> Money:
        """Calculate total from all lines."""
        if not self.lines:
            return Money(amount=0.0, currency="USD")

        total = Money(amount=0.0, currency="USD")
        for line in self.lines:
            total = total.add(line.line_total)
        return total


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create value objects
        unit_price_1 = Money(amount=29.99, currency="USD")
        unit_price_2 = Money(amount=49.99, currency="USD")

        shipping_addr = Address(
            street="123 Main St",
            city="San Francisco",
            state="CA",
            postal_code="94102",
            country="USA",
        )

        billing_addr = Address(
            street="456 Oak Ave",
            city="San Francisco",
            state="CA",
            postal_code="94103",
            country="USA",
        )

        # Create order with value objects
        order = Order(
            customer_id="CUST-789",
            shipping_address=shipping_addr,
            billing_address=billing_addr,
        )

        # Add order lines with value objects
        line1 = OrderLine(product_name="Laptop", quantity=1, unit_price=unit_price_1)
        line2 = OrderLine(product_name="Mouse", quantity=2, unit_price=unit_price_2)
        order.add_lines([line1, line2])

        # Display results
        print(f"Order ID: {order.id}")
        print(f"Customer: {order.customer_id}")
        print(f"Shipping: {order.shipping_address.full_address()}")
        print(f"Order total: {order.order_total}")

        # Value objects maintain their behavior
        combined = unit_price_1.add(unit_price_2)
        print(f"Combined price: {combined}")
