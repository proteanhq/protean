"""
Value Object with Methods - Money with Business Logic

This example demonstrates:
- Business logic methods within value object
- Returning new instances (maintaining immutability)
- Validation within methods
- Computed properties

Usage:
    from protean_skills.value_object.assets.value_object_with_methods import Money
"""

from protean import Domain
from protean.fields import Float, HasMany, String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain(__name__)


@domain.value_object
class Money:
    """
    Money value object with business logic.

    Encapsulates currency and amount with operations like add, subtract, multiply.
    All operations return new Money instances (immutability).
    """

    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    def add(self, other: "Money") -> "Money":
        """Add two Money values, ensuring same currency."""
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot add different currencies: {self.currency} and {other.currency}"
            )
        return Money(currency=self.currency, amount=self.amount + other.amount)

    def subtract(self, other: "Money") -> "Money":
        """Subtract two Money values, ensuring same currency."""
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot subtract different currencies: {self.currency} and {other.currency}"
            )
        return Money(currency=self.currency, amount=self.amount - other.amount)

    def multiply(self, factor: float) -> "Money":
        """Multiply money by a factor."""
        return Money(currency=self.currency, amount=self.amount * factor)

    @property
    def is_positive(self) -> bool:
        """Check if amount is positive."""
        return self.amount > 0

    @property
    def is_zero(self) -> bool:
        """Check if amount is zero."""
        return self.amount == 0


@domain.entity(part_of="Order")
class LineItem:
    """LineItem entity using Money value object."""

    product_id: String(required=True, max_length=50)
    quantity: Float(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def total(self) -> Money:
        """Calculate line item total."""
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    """Order aggregate demonstrating Money usage."""

    order_number: String(required=True, max_length=50, identifier=True)
    customer_id: String(required=True, max_length=50)
    line_items = HasMany(LineItem)

    @property
    def order_total(self) -> Money:
        """Calculate order total by summing line items."""
        if not self.line_items:
            return Money(currency="USD", amount=0.0)

        total = self.line_items[0].total
        for item in self.line_items[1:]:
            total = total.add(item.total)

        return total


if __name__ == "__main__":
    # Create Money instances
    price1 = Money(currency="USD", amount=float("10.00"))
    price2 = Money(currency="USD", amount=float("20.00"))

    print(f"Price 1: {price1.currency} {price1.amount}")
    print(f"Price 2: {price2.currency} {price2.amount}")

    # Add money
    total = price1.add(price2)
    print(f"Total: {total.currency} {total.amount}")

    # Subtract money
    difference = price2.subtract(price1)
    print(f"Difference: {difference.currency} {difference.amount}")

    # Multiply money
    doubled = price1.multiply(float("2"))
    print(f"Doubled: {doubled.currency} {doubled.amount}")

    # Check properties
    print(f"Is positive: {price1.is_positive}")
    zero_money = Money(currency="USD", amount=float("0.00"))
    print(f"Zero money is zero: {zero_money.is_zero}")

    # Cannot add different currencies
    euro_price = Money(currency="EUR", amount=float("10.00"))
    try:
        price1.add(euro_price)
    except ValueError as e:
        print(f"\nCurrency mismatch prevented: {e}")

    # Use in entities
    print("\n--- Line Item Example ---")
    item1 = LineItem(
        product_id="PROD-001",
        quantity=float("3"),
        unit_price=Money(currency="USD", amount=float("15.50")),
    )
    item2 = LineItem(
        product_id="PROD-002",
        quantity=float("2"),
        unit_price=Money(currency="USD", amount=float("25.00")),
    )

    print(f"Item 1 total: {item1.total.currency} {item1.total.amount}")
    print(f"Item 2 total: {item2.total.currency} {item2.total.amount}")

    # Calculate order total
    order = Order(order_number="ORD-001", customer_id="CUST-123")
    order.add_line_items([item1, item2])
    order_total = order.order_total
    print(f"Order total: {order_total.currency} {order_total.amount}")
