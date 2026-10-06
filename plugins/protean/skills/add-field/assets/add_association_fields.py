"""
Adding Association Fields

This example demonstrates:
- HasOne relationships (one-to-one with entities)
- HasMany relationships (one-to-many with entities)
- Auto-generated helper methods for HasMany
- Accessing and manipulating associations
- Custom methods that use auto-generated helpers
- Linking to another aggregate with an Identifier field that holds its id

Usage:
    python add_association_fields.py
"""

from decimal import Decimal as D

from protean import Domain
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import Decimal, HasMany, HasOne, Identifier, Integer, List, String

# Domain setup
domain = Domain()


# ========================================
# Example 1: HasOne (One-to-One Relationship)
# ========================================


@domain.aggregate
class Order:
    """Order aggregate with one-to-one shipping info relationship."""

    order_number: String(required=True, max_length=50, identifier=True)
    customer_id: Identifier(required=True)  # Links to the Customer aggregate by id
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
    - get_one_from_items(id=item_id): Get one item by keyword criteria.
      Raises ObjectNotFoundError when nothing matches.
    - filter_items(**criteria): Get the items whose fields equal the given
      values (equality only, no operators such as unit_price__gt)
    """

    cart_id: String(required=True, max_length=50, identifier=True)
    customer_id: Identifier(required=True)  # Links to the Customer aggregate by id

    # HasMany: One cart has many items
    items = HasMany("CartItem")

    @property
    def total_items(self) -> int:
        """Count total items (considering quantity)."""
        return sum(item.quantity for item in self.items)

    @property
    def subtotal(self) -> D:
        """Calculate cart subtotal."""
        return sum((item.line_total for item in self.items), D("0"))


@domain.entity(part_of="ShoppingCart")
class CartItem:
    """Cart item entity."""

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(required=True, precision=19, scale=4, min_value=0.01)

    @property
    def line_total(self) -> D:
        """Calculate line total."""
        return self.quantity * self.unit_price


# ========================================
# Example 3: Multiple HasMany Relationships
# ========================================


@domain.aggregate
class BlogPost:
    """Blog post with comments, attachments and tags.

    Demonstrates multiple HasMany relationships. Tags are plain strings with
    no identity, so they use a List instead of HasMany.
    """

    title: String(required=True, max_length=200)
    content: String(required=True, max_length=10000)
    author_id: Identifier(required=True)  # Links to the User aggregate by id

    # Multiple HasMany relationships
    comments = HasMany("Comment")
    attachments = HasMany("Attachment")

    # Simple values without identity
    tags: List(content_type=String)

    @property
    def comment_count(self) -> int:
        """Count comments."""
        return len(self.comments)

    @property
    def attachment_names(self) -> list:
        """Get list of attachment file names."""
        return [attachment.file_name for attachment in self.attachments]


@domain.entity(part_of="BlogPost")
class Comment:
    """Comment entity."""

    author_name: String(required=True, max_length=100)
    content: String(required=True, max_length=1000)
    created_at: String(required=True)  # Simplified for example


@domain.entity(part_of="BlogPost")
class Attachment:
    """Attachment entity."""

    file_name: String(required=True, max_length=255)
    size_bytes: Integer(required=True, min_value=0)


# ========================================
# Example 4: Custom Methods with Auto-Generated Helpers
# ========================================


@domain.aggregate
class Invoice:
    """Invoice with line items.

    Shows how to create custom methods that use auto-generated helpers.
    """

    invoice_number: String(required=True, max_length=50, identifier=True)
    customer_id: Identifier(required=True)  # Links to the Customer aggregate by id
    status: String(default="draft", choices=["draft", "sent", "paid", "overdue"])

    # HasMany relationship (auto-generates add_line_items, remove_line_items, etc.)
    line_items = HasMany("InvoiceLineItem")

    def add_product_line(self, description: str, quantity: int, unit_price: D):
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

    def remove_product_line(self, line_id: str):
        """Custom method to remove line item by ID.

        Uses auto-generated get_one_from_line_items() and remove_line_items().
        get_one_from_line_items() takes keyword criteria and raises
        ObjectNotFoundError when no line matches; it never returns None.
        """
        # Use auto-generated helper to find
        try:
            line = self.get_one_from_line_items(id=line_id)
        except ObjectNotFoundError:
            raise ValidationError({"line_items": [f"No line item with id {line_id}"]})

        # Use auto-generated helper to remove
        self.remove_line_items(line)

    @property
    def total(self) -> D:
        """Calculate invoice total."""
        return sum((item.line_total for item in self.line_items), D("0"))


@domain.entity(part_of="Invoice")
class InvoiceLineItem:
    """Invoice line item entity."""

    description: String(required=True, max_length=500)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(required=True, precision=19, scale=4, min_value=0.01)

    @property
    def line_total(self) -> D:
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
                unit_price=D("29.99"),
            ),
            CartItem(
                product_id="PROD-002",
                product_name="Keyboard",
                quantity=1,
                unit_price=D("79.99"),
            ),
            CartItem(
                product_id="PROD-003",
                product_name="USB Cable",
                quantity=3,
                unit_price=D("9.99"),
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

        # Add attachments (auto-generated add_attachments())
        post.add_attachments(
            [
                Attachment(file_name="diagram.png", size_bytes=48213),
                Attachment(file_name="example.py", size_bytes=1820),
            ]
        )  # Auto-generated

        # Tags are a plain list
        post.tags = ["python", "ddd", "protean"]

        print(f"Post: {post.title}")
        print(f"Comments: {post.comment_count}")
        for comment in post.comments:
            print(f"  - {comment.author_name}: {comment.content}")
        print()
        print(f"Attachments: {', '.join(post.attachment_names)}")
        print(f"Tags: {', '.join(post.tags)}")
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
        invoice.add_product_line(
            "Consulting Services", quantity=10, unit_price=D("150.00")
        )
        invoice.add_product_line("Software License", quantity=1, unit_price=D("499.99"))
        invoice.add_product_line(
            "Support (monthly)", quantity=12, unit_price=D("99.99")
        )

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
                    unit_price=D("29.99"),
                ),
                CartItem(
                    product_id="PROD-004",
                    product_name="Monitor",
                    quantity=1,
                    unit_price=D("299.99"),
                ),
                CartItem(
                    product_id="PROD-005",
                    product_name="Webcam",
                    quantity=2,
                    unit_price=D("89.99"),
                ),
            ]
        )

        print("All items in cart:")
        for item in cart2.items:
            print(f"  - {item.product_name}: ${item.unit_price:.2f}")
        print()

        # filter_items() matches on equality only
        monitors = cart2.filter_items(product_id="PROD-004")
        print(f"Items with product PROD-004: {[i.product_name for i in monitors]}")

        # For comparisons, filter the collection in Python
        expensive = [i for i in cart2.items if i.unit_price > D("50")]
        print(f"Items over $50: {[i.product_name for i in expensive]}")

        # get_one_from_items() takes keyword criteria
        webcam = cart2.get_one_from_items(id=expensive[1].id)
        print(f"Found by id: {webcam.product_name}")

        # A miss raises ObjectNotFoundError
        try:
            cart2.get_one_from_items(id="no-such-item")
        except ObjectNotFoundError:
            print("No item with id 'no-such-item'")
        print()

        print("=" * 60)
        print("Demo completed!")
        print("=" * 60)
