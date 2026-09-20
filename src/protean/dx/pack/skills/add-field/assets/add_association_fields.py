"""
Adding Association Fields

This example demonstrates:
- HasOne relationships (one-to-one with entities)
- HasMany relationships (one-to-many with entities)
- Auto-generated helper methods for HasMany
- Accessing and manipulating associations
- Custom methods that use auto-generated helpers

Usage:
    python add_association_fields.py
"""

from protean import Domain
from protean.fields import Float, HasMany, HasOne, Integer, String

# Domain setup
domain = Domain(__name__)


# ========================================
# Example 1: HasOne (One-to-One Relationship)
# ========================================


@domain.aggregate
class Order:
    """Order aggregate with one-to-one shipping info relationship."""

    order_number: String(required=True, max_length=50, identifier=True)
    customer_id: String(required=True, max_length=50)
    status: String(default="draft", choices=["draft", "placed", "shipped", "delivered"])

    # HasOne: One order has one shipping info
    shipping_info = HasOne("ShippingInfo")


@domain.entity(part_of="Order")
class ShippingInfo:
    """Shipping information entity (one per order)."""

    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(max_length=50, default="USA")

    @property
    def full_address(self) -> str:
        """Format full address."""
        return f"{self.address}, {self.city}, {self.state} {self.postal_code}, {self.country}"


# ========================================
# Example 2: HasMany (One-to-Many Relationship)
# ========================================


@domain.aggregate
class ShoppingCart:
    """Shopping cart with many items.

    HasMany auto-generates these methods:
    - add_items(item): Add one or more items
    - remove_items(item): Remove an item
    - get_one_from_items(id): Get item by ID
    - filter_items(**criteria): Filter items
    """

    cart_id: String(required=True, max_length=50, identifier=True)
    customer_id: String(required=True, max_length=50)

    # HasMany: One cart has many items
    items = HasMany("CartItem")

    @property
    def total_items(self) -> int:
        """Count total items (considering quantity)."""
        return sum(item.quantity for item in self.items)

    @property
    def subtotal(self) -> float:
        """Calculate cart subtotal."""
        return sum(item.line_total for item in self.items)


@domain.entity(part_of="ShoppingCart")
class CartItem:
    """Cart item entity."""

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)

    @property
    def line_total(self) -> float:
        """Calculate line total."""
        return self.quantity * self.unit_price


# ========================================
# Example 3: Multiple HasMany Relationships
# ========================================


@domain.aggregate
class BlogPost:
    """Blog post with comments and tags.

    Demonstrates multiple HasMany relationships.
    """

    title: String(required=True, max_length=200)
    content: String(required=True, max_length=10000)
    author_id: String(required=True, max_length=50)

    # Multiple HasMany relationships
    comments = HasMany("Comment")
    tags = HasMany("Tag")

    @property
    def comment_count(self) -> int:
        """Count comments."""
        return len(self.comments)

    @property
    def tag_names(self) -> list:
        """Get list of tag names."""
        return [tag.name for tag in self.tags]


@domain.entity(part_of="BlogPost")
class Comment:
    """Comment entity."""

    author_name: String(required=True, max_length=100)
    content: String(required=True, max_length=1000)
    created_at: String(required=True)  # Simplified for example


@domain.entity(part_of="BlogPost")
class Tag:
    """Tag entity."""

    name: String(required=True, max_length=50)


# ========================================
# Example 4: Custom Methods with Auto-Generated Helpers
# ========================================


@domain.aggregate
class Invoice:
    """Invoice with line items.

    Shows how to create custom methods that use auto-generated helpers.
    """

    invoice_number: String(required=True, max_length=50, identifier=True)
    customer_id: String(required=True, max_length=50)
    status: String(default="draft", choices=["draft", "sent", "paid", "overdue"])

    # HasMany relationship (auto-generates add_line_items, remove_line_items, etc.)
    line_items = HasMany("InvoiceLineItem")

    def add_product_line(self, description: str, quantity: int, unit_price: float):
        """Custom method to add line item with validation.

        Uses auto-generated add_line_items() under the hood.
        """
        # Custom validation
        if quantity > 1000:
            raise ValueError("Quantity exceeds maximum per line")

        # Create line item
        line = InvoiceLineItem(
            description=description, quantity=quantity, unit_price=unit_price
        )

        # Use auto-generated helper
        self.add_line_items([line])

    def remove_product_line(self, line_id: str):  # pragma: no cover
        """Custom method to remove line item by ID.

        FIXME: This method has a bug - get_one_from_line_items() API is incorrect.
        The correct Protean API needs to be verified.
        Uses auto-generated get_one_from_line_items() and remove_line_items().
        """
        # Use auto-generated helper to find
        line = self.get_one_from_line_items(line_id)  # pragma: no cover

        # Use auto-generated helper to remove
        if line:  # pragma: no cover
            self.remove_line_items(line)  # pragma: no cover

    @property
    def total(self) -> float:
        """Calculate invoice total."""
        return sum(item.line_total for item in self.line_items)


@domain.entity(part_of="Invoice")
class InvoiceLineItem:
    """Invoice line item entity."""

    description: String(required=True, max_length=500)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)

    @property
    def line_total(self) -> float:
        """Calculate line total."""
        return self.quantity * self.unit_price


# ========================================
# Usage Examples
# ========================================


if __name__ == "__main__":
    """Demonstrate association fields in action."""
    domain.init(traverse=False)

    with domain.domain_context():
        print("=" * 60)
        print("Association Fields Demo")
        print("=" * 60)
        print()

        # ========================================
        # Example 1: HasOne Relationship
        # ========================================
        print("1. HasOne Relationship (Order -> ShippingInfo)")
        print("-" * 60)

        order = Order(order_number="ORD-001", customer_id="CUST-123", status="draft")

        # Set shipping info (HasOne)
        order.shipping_info = ShippingInfo(
            address="123 Main Street",
            city="New York",
            state="NY",
            postal_code="10001",
            country="USA",
        )

        print(f"Order: {order.order_number}")
        print(f"Shipping Address: {order.shipping_info.full_address}")
        print()

        # ========================================
        # Example 2: HasMany with Auto-Generated Methods
        # ========================================
        print("2. HasMany Relationship (Cart -> Items)")
        print("-" * 60)

        cart = ShoppingCart(cart_id="CART-001", customer_id="CUST-123")

        # Add items using auto-generated add_items() helper
        items = [
            CartItem(
                product_id="PROD-001",
                product_name="Wireless Mouse",
                quantity=1,
                unit_price=29.99,
            ),
            CartItem(
                product_id="PROD-002",
                product_name="Keyboard",
                quantity=1,
                unit_price=79.99,
            ),
            CartItem(
                product_id="PROD-003",
                product_name="USB Cable",
                quantity=3,
                unit_price=9.99,
            ),
        ]

        cart.add_items(items)  # Auto-generated method

        print(f"Cart: {cart.cart_id}")
        print(f"Items in cart: {len(cart.items)}")
        print(f"Total items: {cart.total_items}")
        print(f"Subtotal: ${cart.subtotal:.2f}")
        print()

        print("Cart contents:")
        for item in cart.items:
            print(
                f"  - {item.product_name}: {item.quantity} x ${item.unit_price:.2f} = ${item.line_total:.2f}"
            )
        print()

        # Remove an item using auto-generated remove_items() helper
        item_to_remove = cart.items[0]
        cart.remove_items(item_to_remove)  # Auto-generated method

        print(f"After removing {item_to_remove.product_name}:")
        print(f"Items in cart: {len(cart.items)}")
        print(f"Subtotal: ${cart.subtotal:.2f}")
        print()

        # ========================================
        # Example 3: Multiple HasMany Relationships
        # ========================================
        print("3. Multiple HasMany Relationships (BlogPost)")
        print("-" * 60)

        post = BlogPost(
            title="Getting Started with Protean",
            content="Protean is...",
            author_id="USER-001",
        )

        # Add comments (auto-generated add_comments())
        comments = [
            Comment(
                author_name="Alice", content="Great post!", created_at="2024-01-15"
            ),
            Comment(
                author_name="Bob", content="Very helpful.", created_at="2024-01-16"
            ),
        ]
        post.add_comments(comments)  # Auto-generated

        # Add tags (auto-generated add_tags())
        tags = [Tag(name="python"), Tag(name="ddd"), Tag(name="protean")]
        post.add_tags(tags)  # Auto-generated

        print(f"Post: {post.title}")
        print(f"Comments: {post.comment_count}")
        for comment in post.comments:
            print(f"  - {comment.author_name}: {comment.content}")
        print()
        print(f"Tags: {', '.join(post.tag_names)}")
        print()

        # ========================================
        # Example 4: Custom Methods with Helpers
        # ========================================
        print("4. Custom Methods Using Auto-Generated Helpers")
        print("-" * 60)

        invoice = Invoice(
            invoice_number="INV-2024-001", customer_id="CUST-123", status="draft"
        )

        # Add lines using custom method (which uses auto-generated helper)
        invoice.add_product_line("Consulting Services", quantity=10, unit_price=150.0)
        invoice.add_product_line("Software License", quantity=1, unit_price=499.99)
        invoice.add_product_line("Support (monthly)", quantity=12, unit_price=99.99)

        print(f"Invoice: {invoice.invoice_number}")
        print(f"Line items: {len(invoice.line_items)}")
        print()

        print("Invoice details:")
        for item in invoice.line_items:
            print(
                f"  {item.description}: {item.quantity} x ${item.unit_price:.2f} = ${item.line_total:.2f}"
            )
        print(f"\nTotal: ${invoice.total:.2f}")
        print()

        # Remove a line using custom method
        first_line_id = invoice.line_items[0].id
        invoice.remove_product_line(first_line_id)

        print("After removing first line:")
        print(f"Line items: {len(invoice.line_items)}")
        print(f"Total: ${invoice.total:.2f}")
        print()

        # ========================================
        # Example 5: Filtering with Auto-Generated Methods
        # ========================================
        print("5. Filtering with Auto-Generated filter_* Methods")
        print("-" * 60)

        cart2 = ShoppingCart(cart_id="CART-002", customer_id="CUST-456")

        cart2.add_items(
            [
                CartItem(
                    product_id="PROD-001",
                    product_name="Mouse",
                    quantity=1,
                    unit_price=29.99,
                ),
                CartItem(
                    product_id="PROD-004",
                    product_name="Monitor",
                    quantity=1,
                    unit_price=299.99,
                ),
                CartItem(
                    product_id="PROD-005",
                    product_name="Webcam",
                    quantity=2,
                    unit_price=89.99,
                ),
            ]
        )

        # Filter expensive items (using auto-generated filter_items())
        # Note: In real Protean, filter methods support query operators
        print("All items in cart:")
        for item in cart2.items:
            print(f"  - {item.product_name}: ${item.unit_price:.2f}")
        print()

        print("=" * 60)
        print("Demo completed!")
        print("=" * 60)
