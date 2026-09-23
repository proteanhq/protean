"""
Value Objects in Aggregates - Integration Example

This example demonstrates:
- Embedding value objects in aggregates
- Multiple value objects in same aggregate
- Value object in aggregate methods
- Business logic using value objects
- Complete real-world scenario

Usage:
    from protean_skills.value_object.assets.value_object_in_aggregate import Order
"""

from protean import Domain
from protean.fields import DateTime, HasMany, Integer, String, ValueObject
from protean.utils import utcnow_func

# Domain setup (required for runnable examples)
domain = Domain(__name__)


@domain.value_object
class Money:
    """Money value object with currency and amount."""

    currency: String(max_length=3, default="USD")
    amount: Integer(default=0)

    def add(self, other: "Money") -> "Money":
        """Add two Money values."""
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(currency=self.currency, amount=self.amount + other.amount)

    def multiply(self, factor: int) -> "Money":
        """Multiply money by a factor."""
        return Money(currency=self.currency, amount=self.amount * factor)


@domain.value_object
class Address:
    """Shipping address value object."""

    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

    @property
    def full_address(self) -> str:
        """Return formatted address."""
        return f"{self.street}, {self.city}, {self.state} {self.postal_code}, {self.country}"


@domain.entity(part_of="Order")
class OrderLine:
    """Order line item using Money value object."""

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=100)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        """Calculate line total."""
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    """
    Order aggregate demonstrating multiple value objects.

    Uses:
    - Money for financial amounts
    - Address for shipping
    - OrderLine entities that also use Money
    """

    order_number: String(required=True, max_length=20, identifier=True)
    customer_id: String(required=True, max_length=50)

    # Value objects in aggregate
    shipping_address = ValueObject(Address, required=True)
    total_amount = ValueObject(Money, required=True)

    # Entity collection (entities also use value objects)
    line_items = HasMany(OrderLine)

    # Status and timestamps
    status: String(
        max_length=20,
        choices=["pending", "confirmed", "shipped", "delivered"],
        default="pending",
    )
    created_at: DateTime(default=utcnow_func)

    def calculate_total(self) -> Money:
        """
        Calculate order total from line items.

        Business logic using value objects - demonstrates how aggregates
        work with value objects to implement domain rules.
        """
        if not self.line_items:
            return Money(currency="USD", amount=0)

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total

    def update_total(self):
        """Update total amount based on current line items."""
        self.total_amount = self.calculate_total()

    def confirm(self):
        """
        Confirm the order.

        Business rule: Can only confirm orders with line items.
        Updates total amount based on line items.
        """
        if not self.line_items:
            raise ValueError("Order cannot be confirmed without line items")

        # Calculate and set total
        self.update_total()

        # Update status
        self.status = "confirmed"

    def confirm_order(self):
        """
        Confirm the order.

        Business rule: Can only confirm pending orders.
        Updates total amount based on line items.
        """
        if self.status != "pending":
            raise ValueError(f"Cannot confirm order in status: {self.status}")

        # Calculate and set total
        self.total_amount = self.calculate_total()

        # Update status
        self.status = "confirmed"

    def ship_order(self):
        """Ship the order."""
        if self.status != "confirmed":
            raise ValueError(f"Cannot ship order in status: {self.status}")

        self.status = "shipped"

    def update_shipping_address(self, new_address: Address):
        """
        Update shipping address.

        Business rule: Cannot update address for shipped orders.
        Demonstrates replacing entire value object (immutability).
        """
        if self.status in ["shipped", "delivered"]:
            raise ValueError("Cannot update address for shipped/delivered orders")

        self.shipping_address = new_address


if __name__ == "__main__":
    # Create an order with value objects
    order = Order(
        order_number="ORD-2024-001",
        customer_id="CUST-123",
        shipping_address=Address(
            street="123 Main Street",
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="USA",
        ),
        total_amount=Money(currency="USD", amount=0),  # Will be calculated
    )

    print(f"Order: {order.order_number}")
    print(f"Customer: {order.customer_id}")
    print(f"Shipping to: {order.shipping_address.full_address}")
    print(f"Status: {order.status}")

    # Add line items (entities with value objects)
    order.add_line_items(
        OrderLine(
            product_id="PROD-001",
            product_name="Laptop",
            quantity=1,
            unit_price=Money(currency="USD", amount=1200),
        )
    )
    order.add_line_items(
        OrderLine(
            product_id="PROD-002",
            product_name="Mouse",
            quantity=2,
            unit_price=Money(currency="USD", amount=25),
        )
    )

    print("\n--- Line Items ---")
    for item in order.line_items:
        print(
            f"  {item.product_name}: {item.quantity} x {item.unit_price.amount} = {item.line_total.amount}"
        )

    # Confirm order (calculates total)
    order.confirm_order()
    print("\nOrder confirmed!")
    print(f"Total: {order.total_amount.currency} {order.total_amount.amount}")
    print(f"Status: {order.status}")

    # Try to update address (allowed for confirmed orders)
    new_address = Address(
        street="456 Oak Avenue",
        city="Springfield",
        state="IL",
        postal_code="62702",
        country="USA",
    )
    order.update_shipping_address(new_address)
    print(f"\nAddress updated to: {order.shipping_address.full_address}")

    # Ship order
    order.ship_order()
    print(f"Order shipped! Status: {order.status}")

    # Try to update address after shipping (not allowed)
    print("\n--- Testing business rules ---")
    try:
        order.update_shipping_address(
            Address(
                street="999 New Street",
                city="Other City",
                state="CA",
                postal_code="90001",
                country="USA",
            )
        )
        print("Should have failed!")
    except ValueError as e:
        print(f"Business rule enforced: {e}")

    # Create order with attribute initialization
    print("\n--- Alternative initialization ---")
    order2 = Order(
        order_number="ORD-2024-002",
        customer_id="CUST-456",
        shipping_address_street="789 Elm Street",
        shipping_address_city="Boston",
        shipping_address_state="MA",
        shipping_address_postal_code="02101",
        shipping_address_country="USA",
        total_amount_currency="USD",
        total_amount_amount=500,
    )
    print(f"Order 2: {order2.order_number}")
    print(f"Shipping to: {order2.shipping_address.full_address}")
    print(f"Total: {order2.total_amount.currency} {order2.total_amount.amount}")
