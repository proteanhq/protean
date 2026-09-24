"""
Adding Simple Fields to Protean Domain Elements

This example demonstrates:
- Adding basic fields to aggregates with built-in validation
- Using field-level validation parameters (min_value, max_value, max_length)
- Setting required/optional fields and defaults
- Adding fields to entities with part_of parameter
- Proper field type selection for different data

Usage:
    python add_simple_field.py
"""

from datetime import UTC, date, datetime

from protean import Domain
from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    ValueObject,
)

# Domain setup
domain = Domain(__name__)


def utc_now():
    """Helper for default timestamp."""
    return datetime.now(UTC)


# ========================================
# Example 1: Adding fields to an aggregate
# ========================================


@domain.aggregate
class Product:
    """Product aggregate with various field types.

    Demonstrates adding fields with proper validation.
    """

    # Text fields with length constraints
    name: String(required=True, max_length=200, min_length=3)
    sku: String(required=True, max_length=50, unique=True)
    description: Text()  # Long text, no length limit

    # Numeric fields with range validation
    price: Float(required=True, min_value=0.01, max_value=999999.99)
    stock_count: Integer(default=0, min_value=0, max_value=100000)
    weight_kg: Float(min_value=0.1, max_value=1000.0)

    # Boolean flags
    is_active: Boolean(default=True)
    is_featured: Boolean(default=False)

    # Date/time fields
    created_at: DateTime(default=utc_now)
    available_from: Date()

    # Enum-like field with choices
    category: String(
        required=True, choices=["electronics", "clothing", "food", "books", "toys"]
    )

    # Percentage field (0-100)
    discount_percent: Float(default=0.0, min_value=0.0, max_value=100.0)


# ========================================
# Example 2: Adding fields to an entity
# ========================================


@domain.aggregate
class Order:
    """Order aggregate containing line item entities."""

    order_number: String(required=True, max_length=50, identifier=True)
    customer_id: String(required=True, max_length=50)
    status: String(
        default="draft",
        choices=["draft", "placed", "shipped", "delivered", "cancelled"],
    )
    created_at: DateTime(default=utc_now)


@domain.entity(part_of="Order")  # Must specify parent aggregate
class LineItem:
    """Line item entity with product and pricing fields.

    Demonstrates adding fields to entities.
    """

    # Product reference
    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)  # Denormalized for display

    # Quantity and pricing
    quantity: Integer(required=True, min_value=1, max_value=1000)
    unit_price: Float(required=True, min_value=0.01)

    # Optional discount
    discount_percent: Float(default=0.0, min_value=0.0, max_value=100.0)

    # Optional notes
    notes: String(max_length=500)

    @property
    def subtotal(self) -> float:
        """Calculate line item subtotal."""
        base = self.quantity * self.unit_price
        discount = base * (self.discount_percent / 100)
        return base - discount


# ========================================
# Example 3: Adding fields to value objects
# ========================================


@domain.value_object
class ContactInfo:
    """Contact information value object.

    Demonstrates adding fields to value objects.
    """

    # Email (use custom validator in real code)
    email: String(required=True, max_length=254)

    # Phone (use custom validator in real code)
    phone: String(max_length=20)

    # Website
    website: String(max_length=255)


@domain.aggregate
class Customer:
    """Customer aggregate using ContactInfo value object."""

    customer_id: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=100)

    # Embedded value object: the ContactInfo fields live under `contact`
    contact: ValueObject(ContactInfo, required=True)


# ========================================
# Usage Examples
# ========================================

if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create product with various field types
        product = Product(
            name="Wireless Mouse",
            sku="MOUSE-001",
            description="Ergonomic wireless mouse with USB receiver",
            price=29.99,
            stock_count=50,
            weight_kg=0.15,
            category="electronics",
            is_active=True,
            is_featured=True,
            available_from=date.today(),
            discount_percent=10.0,
        )

        print("Product created:")
        print(f"  Name: {product.name}")
        print(f"  SKU: {product.sku}")
        print(f"  Price: ${product.price:.2f}")
        print(f"  Discount: {product.discount_percent}%")
        print(f"  Stock: {product.stock_count} units")
        print(f"  Weight: {product.weight_kg} kg")
        print(f"  Category: {product.category}")
        print(f"  Active: {product.is_active}")
        print(f"  Featured: {product.is_featured}")
        print()

        # Create order with line items
        order = Order(
            order_number="ORD-2024-001", customer_id="CUST-123", status="draft"
        )

        # Add line item (in real code, use HasMany field)
        line_item = LineItem(
            product_id="PROD-001",
            product_name="Wireless Mouse",
            quantity=2,
            unit_price=29.99,
            discount_percent=10.0,
            notes="Gift wrap requested",
        )

        print("Order created:")
        print(f"  Order Number: {order.order_number}")
        print(f"  Customer: {order.customer_id}")
        print(f"  Status: {order.status}")
        print()

        print("Line Item:")
        print(f"  Product: {line_item.product_name}")
        print(f"  Quantity: {line_item.quantity}")
        print(f"  Unit Price: ${line_item.unit_price:.2f}")
        print(f"  Discount: {line_item.discount_percent}%")
        print(f"  Subtotal: ${line_item.subtotal:.2f}")
        print(f"  Notes: {line_item.notes}")
        print()

        # Demonstrate field validation
        print("Testing field validation:")

        # Valid: within range
        try:
            valid_product = Product(
                name="Test Product",
                sku="TEST-001",
                price=50.0,  # Valid: between 0.01 and 999999.99
                category="electronics",
            )
            print("  ✓ Valid price accepted")
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")

        # Invalid: below minimum
        try:
            invalid_product = Product(
                name="Test Product",
                sku="TEST-002",
                price=0.0,  # Invalid: below min_value=0.01
                category="electronics",
            )
            print("  ✗ Invalid price was accepted (should have failed!)")
        except Exception:
            print("  ✓ Invalid price rejected: Price below minimum")

        # Invalid: missing required field
        try:
            incomplete_product = Product(
                name="Test Product"
                # Missing required 'sku' and 'category'
            )
            print("  ✗ Missing required fields accepted (should have failed!)")
        except Exception:
            print("  ✓ Missing required fields rejected")
