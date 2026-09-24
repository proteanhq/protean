"""
Value Objects in Entities - Integration Example

This example demonstrates:
- Embedding value objects in entities
- Value objects in entities that are part of aggregates
- Entities with value objects accessed through aggregates
- Real-world scenario: Order with LineItems containing Money

Usage:
    from protean_skills.value_object.assets.value_object_in_entity import Order
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Integer, String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain(__name__)


@domain.value_object
class Money:
    """Money value object."""

    currency: String(max_length=3, default="USD")
    amount: Float(default=0.0)

    def add(self, other: "Money") -> "Money":
        """Add two Money values."""
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(currency=self.currency, amount=self.amount + other.amount)

    def multiply(self, factor: float) -> "Money":
        """Multiply money by a factor."""
        return Money(currency=self.currency, amount=self.amount * factor)


@domain.value_object
class Dimensions:
    """Product dimensions value object."""

    length: Float(required=True)  # in cm
    width: Float(required=True)  # in cm
    height: Float(required=True)  # in cm
    weight: Float(required=True)  # in kg

    @property
    def volume(self) -> float:
        """Calculate volume in cubic cm."""
        return self.length * self.width * self.height


@domain.entity(part_of="Order")
class LineItem:
    """
    LineItem entity with value objects.

    Entities can contain value objects just like aggregates.
    This entity is accessed through the Order aggregate.
    """

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=100)
    quantity: Integer(required=True, min_value=1)

    # Value objects in entity
    unit_price = ValueObject(Money, required=True)
    dimensions = ValueObject(Dimensions)

    @property
    def line_total(self) -> Money:
        """Calculate line total (quantity * unit_price)."""
        return self.unit_price.multiply(self.quantity)

    @property
    def total_volume(self) -> float:
        """Calculate total volume for all items in this line."""
        if self.dimensions:
            return self.dimensions.volume * self.quantity
        return 0.0


@domain.entity(part_of="Invoice")
class InvoiceLine:
    """
    InvoiceLine entity for invoicing scenario.

    Demonstrates value objects in entities in a different context.
    """

    description: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)
    discount = ValueObject(Money)  # Optional discount

    @invariant.post
    def discount_currency_matches_unit_price(self):
        """Ensure discount currency matches unit_price currency."""
        if (
            self.discount
            and self.unit_price
            and self.discount.currency != self.unit_price.currency
        ):
            raise ValidationError(
                {"discount": ["Discount currency must match unit price currency"]}
            )

    @property
    def subtotal(self) -> Money:
        """Calculate subtotal before discount."""
        return self.unit_price.multiply(self.quantity)

    @property
    def total(self) -> Money:
        """Calculate total after discount."""
        subtotal = self.subtotal
        if self.discount:
            # Currency matching is guaranteed by invariant
            return Money(
                currency=subtotal.currency,
                amount=subtotal.amount - self.discount.amount,
            )
        return subtotal


@domain.aggregate
class Order:
    """Order aggregate containing LineItem entities with value objects."""

    order_number: String(required=True, max_length=20, identifier=True)
    customer_id: String(required=True, max_length=50)
    line_items = HasMany(LineItem)

    @property
    def order_total(self) -> Money:
        """Calculate order total from line items."""
        if not self.line_items:
            return Money(currency="USD", amount=0.0)

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total

    @property
    def total_volume(self) -> float:
        """Calculate total volume of all items."""
        return sum(item.total_volume for item in self.line_items)

    @property
    def item_count(self) -> int:
        """Get total quantity of all items."""
        return sum(item.quantity for item in self.line_items)

    def total(self) -> Money:
        """Calculate order total from line items (method version)."""
        return self.order_total


@domain.aggregate
class Invoice:
    """Invoice aggregate containing InvoiceLine entities."""

    invoice_number: String(required=True, max_length=20, identifier=True)
    customer_id: String(required=True, max_length=50)
    invoice_lines = HasMany(InvoiceLine)

    @property
    def invoice_total(self) -> Money:
        """Calculate invoice total."""
        if not self.invoice_lines:
            return Money(currency="USD", amount=0.0)

        total = self.invoice_lines[0].total
        for line in self.invoice_lines[1:]:
            total = total.add(line.total)

        return total

    def total(self) -> Money:
        """Calculate invoice total (method version)."""
        return self.invoice_total


if __name__ == "__main__":
    # Create order with line items containing value objects
    order = Order(order_number="ORD-001", customer_id="CUST-123")

    # Add line item with value objects
    order.add_line_items(
        LineItem(
            product_id="PROD-001",
            product_name="Laptop",
            quantity=2,
            unit_price=Money(currency="USD", amount=1200.0),
            dimensions=Dimensions(length=35.0, width=25.0, height=2.0, weight=2.5),
        )
    )

    order.add_line_items(
        LineItem(
            product_id="PROD-002",
            product_name="Mouse",
            quantity=3,
            unit_price=Money(currency="USD", amount=25.0),
            dimensions=Dimensions(length=10.0, width=6.0, height=4.0, weight=0.1),
        )
    )

    print(f"Order: {order.order_number}")
    print(f"Customer: {order.customer_id}")
    print("\n--- Line Items ---")

    for item in order.line_items:
        print(f"  {item.product_name}:")
        print(f"    Quantity: {item.quantity}")
        print(f"    Unit Price: {item.unit_price.currency} {item.unit_price.amount}")
        print(f"    Line Total: {item.line_total.currency} {item.line_total.amount}")
        if item.dimensions:
            print(
                f"    Dimensions: {item.dimensions.length}x{item.dimensions.width}x{item.dimensions.height} cm"
            )
            print(f"    Volume per unit: {item.dimensions.volume:.2f} cm³")
            print(f"    Total volume: {item.total_volume:.2f} cm³")

    # Calculate order totals
    order_total = order.total()
    order_volume = order.total_volume()
    print(f"\nOrder Total: {order_total.currency} {order_total.amount}")
    print(f"Total Volume: {order_volume:.2f} cm³")

    # Initialize entity value objects by attributes
    print("\n--- Alternative Initialization ---")
    order2 = Order(order_number="ORD-002", customer_id="CUST-456")

    order2.add_line_items(
        LineItem(
            product_id="PROD-003",
            product_name="Keyboard",
            quantity=1,
            unit_price_currency="USD",
            unit_price_amount=75.0,
            dimensions_length=45.0,
            dimensions_width=15.0,
            dimensions_height=3.0,
            dimensions_weight=0.8,
        )
    )

    item = order2.line_items[0]
    print(f"Item: {item.product_name}")
    print(f"Price: {item.unit_price.currency} {item.unit_price.amount}")
    print(f"Volume: {item.dimensions.volume:.2f} cm³")

    # Invoice example with discounts
    print("\n--- Invoice Example ---")
    invoice = Invoice(invoice_number="INV-001", customer_id="CUST-123")

    invoice.add_invoice_lines(
        InvoiceLine(
            description="Consulting Services - 10 hours",
            quantity=10,
            unit_price=Money(currency="USD", amount=150.0),
            discount=Money(currency="USD", amount=100.0),  # Bulk discount
        )
    )

    invoice.add_invoice_lines(
        InvoiceLine(
            description="Software License",
            quantity=1,
            unit_price=Money(currency="USD", amount=500.0),
            # No discount
        )
    )

    print(f"Invoice: {invoice.invoice_number}")
    print("\n--- Invoice Lines ---")

    for line in invoice.invoice_lines:
        print(f"  {line.description}:")
        print(f"    Quantity: {line.quantity}")
        print(f"    Unit Price: {line.unit_price.currency} {line.unit_price.amount}")
        print(f"    Subtotal: {line.subtotal.currency} {line.subtotal.amount}")
        if line.discount:
            print(f"    Discount: {line.discount.currency} {line.discount.amount}")
        print(f"    Total: {line.total.currency} {line.total.amount}")

    invoice_total = invoice.total()
    print(f"\nInvoice Total: {invoice_total.currency} {invoice_total.amount}")
