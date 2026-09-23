"""
Adding ValueObject Fields

This example demonstrates:
- Creating value objects for complex immutable data
- Adding ValueObject fields to aggregates and entities
- Initializing value objects (by object or by attributes)
- Value object immutability and replacement
- Value objects with behavior (methods)
- Nested value objects
- Common value object patterns (Money, Address, Email)

Usage:
    python add_value_object_field.py
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Integer, String, ValueObject

# Domain setup
domain = Domain(__name__)


# ========================================
# Value Objects
# ========================================


@domain.value_object
class Money:
    """Money value object with amount and currency.

    Demonstrates:
    - Multiple related attributes (amount + currency)
    - Immutability
    - Behavior (add, multiply methods)
    """

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        """Add two Money values.

        Returns NEW instance (value objects are immutable).
        """
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def multiply(self, factor: float) -> "Money":
        """Multiply money by a factor.

        Returns NEW instance.
        """
        return Money(amount=self.amount * factor, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        """Subtract money.

        Returns NEW instance.
        """
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract {other.currency} from {self.currency}")
        return Money(amount=self.amount - other.amount, currency=self.currency)


@domain.value_object
class Address:
    """Address value object.

    Demonstrates:
    - Multiple string fields for structured data
    - Computed property (full_address)
    """

    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(max_length=50, default="USA")

    @property
    def full_address(self) -> str:
        """Format full address as string."""
        return f"{self.street}, {self.city}, {self.state} {self.postal_code}, {self.country}"


@domain.value_object
class Coordinates:
    """Geographic coordinates value object.

    Demonstrates:
    - Numeric fields with range constraints
    - Validation in value objects
    """

    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)


@domain.value_object
class DateRange:
    """Date range value object with validation.

    Demonstrates:
    - Cross-field validation with invariants
    - Computed property (duration_days)
    """

    start_date: String(required=True)  # Simplified as string for example
    end_date: String(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        """Business rule: end date must be after start date."""
        if self.end_date <= self.start_date:
            raise ValidationError({"_entity": ["End date must be after start date"]})

    @property
    def duration_days(self) -> int:
        """Calculate duration (simplified)."""
        # In real code, parse dates and calculate difference
        return 7  # Placeholder


# ========================================
# Aggregates Using Value Objects
# ========================================


@domain.aggregate
class Order:
    """Order aggregate with multiple value object fields.

    Demonstrates:
    - Multiple ValueObject fields in one aggregate
    - Using value objects in calculated properties
    """

    order_number: String(required=True, max_length=50, identifier=True)
    customer_id: String(required=True, max_length=50)
    status: String(default="draft", choices=["draft", "placed", "shipped", "delivered"])

    # ValueObject fields
    total = ValueObject(Money, required=True)
    shipping_cost = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)

    # Optional value object
    billing_address = ValueObject(Address)

    @property
    def grand_total(self) -> Money:
        """Calculate grand total including shipping.

        Demonstrates using value object methods.
        """
        return self.total.add(self.shipping_cost)


@domain.aggregate
class Product:
    """Product with price as Money value object."""

    sku: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=200)

    # Price as Money (not primitive float)
    price = ValueObject(Money, required=True)

    # Location (optional)
    warehouse_location = ValueObject(Coordinates)

    def apply_discount(self, discount_percent: float):
        """Apply discount to price.

        Demonstrates replacing value object (immutability).
        """
        if not (0 <= discount_percent <= 100):
            raise ValueError("Discount must be between 0 and 100")

        discount_factor = 1 - (discount_percent / 100)
        self.price = self.price.multiply(discount_factor)


@domain.aggregate
class Event:
    """Event with date range value object."""

    event_id: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=200)
    location = ValueObject(Address, required=True)
    date_range = ValueObject(DateRange, required=True)


# ========================================
# Entities Using Value Objects
# ========================================


@domain.entity(part_of="Order")
class LineItem:
    """Line item with Money value object.

    Demonstrates:
    - Value objects in entities
    - Calculations using value object methods
    """

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)

    # Unit price as Money (not primitive)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        """Calculate line total using Money's multiply method."""
        return self.unit_price.multiply(self.quantity)


# ========================================
# Usage Examples
# ========================================


if __name__ == "__main__":
    """Demonstrate value object fields in action."""
    domain.init(traverse=False)

    with domain.domain_context():
        print("=" * 60)
        print("ValueObject Fields Demo")
        print("=" * 60)
        print()

        # ========================================
        # Example 1: Initialize with Object
        # ========================================
        print("1. Initializing with Value Object Instances")
        print("-" * 60)

        order = Order(
            order_number="ORD-001",
            customer_id="CUST-123",
            total=Money(amount=150.0, currency="USD"),
            shipping_cost=Money(amount=10.0, currency="USD"),
            shipping_address=Address(
                street="123 Main St", city="New York", state="NY", postal_code="10001"
            ),
        )

        print(f"Order: {order.order_number}")
        print(f"Total: ${order.total.amount:.2f} {order.total.currency}")
        print(f"Shipping: ${order.shipping_cost.amount:.2f}")
        print(f"Address: {order.shipping_address.full_address}")
        print(f"Grand Total: ${order.grand_total.amount:.2f}")
        print()

        # ========================================
        # Example 2: Initialize by Attributes
        # ========================================
        print("2. Initializing by Flattened Attributes")
        print("-" * 60)

        # Attribute names: {field_name}_{vo_field_name}
        order2 = Order(
            order_number="ORD-002",
            customer_id="CUST-456",
            total_amount=200.0,
            total_currency="USD",
            shipping_cost_amount=15.0,
            shipping_cost_currency="USD",
            shipping_address_street="456 Oak Ave",
            shipping_address_city="Boston",
            shipping_address_state="MA",
            shipping_address_postal_code="02101",
            shipping_address_country="USA",
        )

        print(f"Order: {order2.order_number}")
        print(f"Total: ${order2.total.amount:.2f}")
        print(f"Address: {order2.shipping_address.full_address}")
        print()

        # ========================================
        # Example 3: Value Object Immutability
        # ========================================
        print("3. Value Object Immutability")
        print("-" * 60)

        product = Product(
            sku="PROD-001",
            name="Wireless Mouse",
            price=Money(amount=29.99, currency="USD"),
            warehouse_location=Coordinates(latitude=40.7128, longitude=-74.0060),
        )

        print(f"Product: {product.name}")
        print(f"Original price: ${product.price.amount:.2f}")

        # Apply 20% discount
        product.apply_discount(20.0)
        print(f"After 20% discount: ${product.price.amount:.2f}")

        # Cannot modify value object directly
        print("\nTrying to modify value object directly:")
        try:
            product.price.amount = 50.0  # This will fail!
            print("  ERROR: Should have prevented modification!")
        except Exception:
            print("  ✓ Correctly prevented: Value objects are immutable")

        # Must replace entire value object
        print("\nReplacing value object:")
        product.price = Money(amount=19.99, currency="USD")
        print(f"  New price: ${product.price.amount:.2f}")
        print()

        # ========================================
        # Example 4: Value Object with Behavior
        # ========================================
        print("4. Value Object Methods")
        print("-" * 60)

        price1 = Money(amount=100.0, currency="USD")
        price2 = Money(amount=50.0, currency="USD")

        # Add (returns new Money instance)
        total = price1.add(price2)
        print(f"${price1.amount:.2f} + ${price2.amount:.2f} = ${total.amount:.2f}")

        # Multiply (returns new Money instance)
        doubled = price1.multiply(2)
        print(f"${price1.amount:.2f} x 2 = ${doubled.amount:.2f}")

        # Subtract (returns new Money instance)
        difference = price1.subtract(price2)
        print(f"${price1.amount:.2f} - ${price2.amount:.2f} = ${difference.amount:.2f}")

        # Originals unchanged (immutability)
        print("\nOriginal values unchanged:")
        print(f"  price1: ${price1.amount:.2f}")
        print(f"  price2: ${price2.amount:.2f}")
        print()

        # ========================================
        # Example 5: Currency Mismatch
        # ========================================
        print("5. Currency Validation")
        print("-" * 60)

        usd = Money(amount=100.0, currency="USD")
        eur = Money(amount=100.0, currency="EUR")

        try:
            mixed = usd.add(eur)  # Should fail!
            print("  ERROR: Should have prevented currency mismatch!")
        except ValueError as e:
            print(f"  ✓ Correctly rejected: {e}")
        print()

        # ========================================
        # Example 6: Optional Value Objects
        # ========================================
        print("6. Optional Value Objects")
        print("-" * 60)

        # Order with same billing and shipping
        order4 = Order(
            order_number="ORD-004",
            customer_id="CUST-999",
            total=Money(amount=100.0, currency="USD"),
            shipping_cost=Money(amount=10.0, currency="USD"),
            shipping_address=Address(
                street="789 Pine Rd", city="Seattle", state="WA", postal_code="98101"
            ),
            # billing_address is optional, not provided
        )

        print(f"Order: {order4.order_number}")
        print(f"Shipping: {order4.shipping_address.full_address}")
        print(
            f"Billing: {'Same as shipping' if not order4.billing_address else order4.billing_address.full_address}"
        )
        print()

        # ========================================
        # Example 8: Value Object with Invariants
        # ========================================
        print("8. Value Objects with Validation")
        print("-" * 60)

        # Valid date range
        try:
            event = Event(
                event_id="EVT-001",
                name="Tech Conference",
                location=Address(
                    street="Convention Center",
                    city="San Francisco",
                    state="CA",
                    postal_code="94102",
                ),
                date_range=DateRange(start_date="2024-03-01", end_date="2024-03-03"),
            )
            print(f"✓ Event created: {event.name}")
            print(f"  Duration: {event.date_range.duration_days} days")
        except ValidationError as e:
            print(f"✗ Unexpected error: {e}")

        # Invalid date range (end before start)
        try:
            invalid_event = Event(
                event_id="EVT-002",
                name="Invalid Event",
                location=Address(
                    street="Test", city="Test", state="TE", postal_code="00000"
                ),
                date_range=DateRange(
                    start_date="2024-03-05",
                    end_date="2024-03-01",  # Invalid!
                ),
            )
            print("✗ Should have rejected invalid date range!")
        except ValidationError:
            print("✓ Invalid date range correctly rejected")

        print()
        print("=" * 60)
        print("Demo completed!")
        print("=" * 60)
