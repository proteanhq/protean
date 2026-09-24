"""
Entity containing nested entities (entity with HasMany to other entities).

This example demonstrates:
- Entities containing other entities via HasMany
- Multi-level entity hierarchy within an aggregate
- Navigation through nested entity relationships
- Business logic across multiple entity levels
- Complex aggregate structures with nested entities

Usage:
    order = Order(customer_id="C123")
    item = LineItem(product_id="P1", quantity=2)
    note = LineItemNote(content="Gift wrap please")
    item.add_notes([note])
    order.add_line_items([item])
    domain.repository_for(Order).add(order)
"""

from datetime import datetime

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import DateTime, Float, HasMany, Integer, Reference, String, Text

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """An order aggregate with nested entity structure."""

    order_number: String(required=True, max_length=50, unique=True)
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")
    placed_at: DateTime()

    # One-to-many: order has many line items
    line_items = HasMany("LineItem")

    @property
    def total_amount(self) -> float:
        """Calculate total order amount."""
        if not self.line_items:
            return 0.0
        return sum(item.total for item in self.line_items)

    @property
    def total_notes(self) -> int:
        """Count total notes across all line items."""
        if not self.line_items:
            return 0
        return sum(len(item.notes) if item.notes else 0 for item in self.line_items)

    def get_items_with_notes(self) -> list:
        """Get all line items that have notes."""
        if not self.line_items:
            return []
        return [item for item in self.line_items if item.notes and len(item.notes) > 0]

    def place(self):
        """Place the order."""
        if not self.line_items:
            raise ValueError("Cannot place order without line items")
        self.status = "placed"
        self.placed_at = datetime.now()


@domain.entity(part_of="Order")
class LineItem:
    """A line item that can contain notes and customizations."""

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)

    # Nested entities: line item has many notes
    notes = HasMany("LineItemNote")

    # Nested entities: line item has many customizations
    customizations = HasMany("LineItemCustomization")

    # Reference back to parent aggregate (automatic)
    order = Reference(Order)

    @property
    def subtotal(self) -> float:
        """Calculate line item subtotal."""
        return self.quantity * self.unit_price

    @property
    def customization_fee(self) -> float:
        """Calculate total customization fees."""
        if not self.customizations:
            return 0.0
        return sum(c.price for c in self.customizations)

    @property
    def total(self) -> float:
        """Calculate total including customizations."""
        return self.subtotal + self.customization_fee

    @property
    def has_special_instructions(self) -> bool:
        """Check if item has any special notes."""
        return self.notes and len(self.notes) > 0

    def add_note(self, content: str, author: str = "Customer"):
        """
        Add a note to this line item.

        Validation (content not empty) is enforced by LineItemNote invariant.
        """
        note = LineItemNote(content=content.strip(), author=author)
        self.add_notes([note])

    def add_customization(
        self, customization_type: str, details: str, price: float = 0.0
    ):
        """
        Add a customization to this line item.

        Validation (customization_type not empty) is enforced by LineItemCustomization invariant.
        """
        custom = LineItemCustomization(
            customization_type=customization_type,
            details=details,
            price=price,
        )
        self.add_customizations([custom])


@domain.entity(part_of="Order")
class LineItemNote:
    """A note attached to a line item."""

    content: Text(required=True)
    author: String(max_length=100, default="Customer")
    created_at: DateTime(default=datetime.now)

    # Reference back to parent LineItem
    line_item = Reference("LineItem")

    @invariant.post
    def content_not_empty(self):
        """Ensure note content is not empty."""
        if not self.content or not self.content.strip():
            raise ValidationError({"content": ["Note content cannot be empty"]})

    @property
    def preview(self) -> str:
        """Get a preview of the note (first 50 chars)."""
        if len(self.content) <= 50:
            return self.content
        return self.content[:47] + "..."


@domain.entity(part_of="Order")
class LineItemCustomization:
    """A customization option for a line item."""

    customization_type: String(
        required=True, max_length=50
    )  # e.g., "engraving", "color", "size"
    details: Text(required=True)
    price: Float(default=0.0, min_value=0.0)

    # Reference back to parent LineItem
    line_item = Reference("LineItem")

    @invariant.post
    def customization_type_not_empty(self):
        """Ensure customization type is not empty."""
        if not self.customization_type or not self.customization_type.strip():
            raise ValidationError(
                {"customization_type": ["Customization type cannot be empty"]}
            )

    @property
    def description(self) -> str:
        """Get formatted description."""
        fee_text = f" (+${self.price:.2f})" if self.price > 0 else ""
        return f"{self.customization_type}: {self.details}{fee_text}"


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an order
        order = Order(
            order_number="ORD-2024-001",
            customer_id="CUST-12345",
        )

        # Create first line item with notes and customizations
        item1 = LineItem(
            product_id="PROD-001",
            product_name="Custom T-Shirt",
            quantity=2,
            unit_price=29.99,
        )

        # Add notes to the line item (nested entity)
        item1.add_note("Please use soft fabric", "Customer")
        item1.add_note("Gift wrap this item", "Customer")

        # Add customizations to the line item (nested entity)
        item1.add_customization("Color", "Navy Blue", 0.0)
        item1.add_customization("Size", "Large", 0.0)
        item1.add_customization("Engraving", "Happy Birthday!", 5.99)

        # Create second line item
        item2 = LineItem(
            product_id="PROD-002",
            product_name="Coffee Mug",
            quantity=1,
            unit_price=15.99,
        )
        item2.add_customization("Text", "World's Best Developer", 3.99)

        # Add items to order
        order.add_line_items([item1, item2])

        # Display order information
        print(f"Order: {order.order_number}")
        print(f"Customer: {order.customer_id}")
        print(f"Status: {order.status}")
        print(f"Total notes: {order.total_notes}")

        # Display line items with nested entities
        print("\nLine Items:")
        for item in order.line_items:
            print(f"\n  {item.product_name} (x{item.quantity})")
            print(f"    Base price: ${item.subtotal:.2f}")
            print(f"    Customization fees: ${item.customization_fee:.2f}")
            print(f"    Total: ${item.total:.2f}")

            # Display notes (nested entities)
            if item.notes:
                print(f"    Notes ({len(item.notes)}):")
                for note in item.notes:
                    print(f"      - {note.preview} (by {note.author})")

            # Display customizations (nested entities)
            if item.customizations:
                print(f"    Customizations ({len(item.customizations)}):")
                for custom in item.customizations:
                    print(f"      - {custom.description}")

        print(f"\nOrder Total: ${order.total_amount:.2f}")

        # Get items with special instructions
        items_with_notes = order.get_items_with_notes()
        print(f"\nItems with special instructions: {len(items_with_notes)}")

        # Navigate through nested entities
        if order.line_items and order.line_items[0].notes:
            first_note = order.line_items[0].notes[0]
            print(
                f"\nFirst note belongs to line item: {first_note.line_item.product_name}"
            )

        # Place the order
        order.place()
        print(f"\nOrder placed at: {order.placed_at}")
        print(f"Order status: {order.status}")
