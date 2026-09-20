"""
Abstract aggregates and inheritance patterns.

This example demonstrates:
- Abstract aggregate base classes with abstract=True
- Inheriting common fields from abstract aggregates
- auto_add_id_field option for base classes
- Concrete aggregates extending abstract ones
- Multiple aggregates sharing common attributes

Usage:
    user = User(email="john@example.com", name="John Doe")
    article = Article(title="DDD Patterns", content="...", author_id="USER-123")
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Float, String, Text

# Domain setup
domain = Domain()


def utc_now():
    """Helper function to get current UTC time."""
    return datetime.now(UTC)


@domain.aggregate(abstract=True, auto_add_id_field=False)
class TimeStamped:
    """
    Abstract base aggregate with timestamp fields.

    This cannot be instantiated directly and must be subclassed.
    All subclasses will automatically inherit created_at and updated_at.
    Uses auto_add_id_field=False to let subclasses define their own identifiers.
    """

    created_at: DateTime(default=utc_now)
    updated_at: DateTime(default=utc_now)


@domain.aggregate(abstract=True)
class Auditable(TimeStamped):
    """
    Abstract aggregate extending TimeStamped with audit fields.

    Demonstrates multi-level inheritance.
    """

    created_by: String(max_length=100)
    updated_by: String(max_length=100)


@domain.aggregate
class User(TimeStamped):
    """User aggregate inheriting timestamp fields."""

    email: String(required=True, max_length=255, identifier=True)
    name: String(required=True, max_length=200)
    bio: Text()

    def update_profile(self, name: str, bio: str):
        """Update user profile and set updated_at."""
        self.name = name
        self.bio = bio
        self.updated_at = utc_now()


@domain.aggregate(auto_add_id_field=True)
class Article(Auditable):
    """Article aggregate inheriting from Auditable (and TimeStamped).

    Uses auto_add_id_field=True to override parent's setting and get an auto-generated id.
    """

    title: String(required=True, max_length=500)
    content: Text(required=True)
    author_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")

    def publish(self, published_by: str):
        """Publish the article."""
        self.status = "published"
        self.updated_at = utc_now()
        self.updated_by = published_by


@domain.aggregate(abstract=True, auto_add_id_field=False)
class BaseEntity:
    """
    Abstract base with no automatic ID field.

    Use auto_add_id_field=False when you want to control
    the identifier field yourself in subclasses.
    """

    created_at: DateTime(default=utc_now)


@domain.aggregate
class Product(BaseEntity):
    """Product with custom identifier field."""

    # Define our own identifier field
    sku: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=200)
    price: Float()  # Could be Money value object in real app


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        print("=== TimeStamped Inheritance ===")

        # Try to instantiate abstract class (will fail)
        try:
            base = TimeStamped()
        except Exception as e:
            print(f"Cannot instantiate abstract class: {type(e).__name__}")

        # Create concrete class
        user = User(email="john@example.com", name="John Doe", bio="Software developer")

        print(f"User: {user.name}")
        print(f"Created at: {user.created_at}")
        print(f"Has id: {hasattr(user, 'id')}")

        # Update profile (updates updated_at)
        import time

        time.sleep(0.1)  # Small delay to see different timestamp
        user.update_profile(name="John Smith", bio="Senior developer")
        print(f"Updated at: {user.updated_at}")
        print(f"Timestamps differ: {user.created_at != user.updated_at}")

        print("\n=== Auditable Inheritance ===")

        article = Article(
            title="Domain-Driven Design Patterns",
            content="DDD helps us model complex domains...",
            author_id="USER-123",
            created_by="john@example.com",
        )

        print(f"Article: {article.title}")
        print(f"Created at: {article.created_at}")
        print(f"Created by: {article.created_by}")
        print(f"Has updated_by: {hasattr(article, 'updated_by')}")

        # Publish article
        article.publish(published_by="editor@example.com")
        print(f"Status: {article.status}")
        print(f"Updated by: {article.updated_by}")

        print("\n=== Custom Identifier ===")

        product = Product(sku="PROD-12345", name="Wireless Mouse", price=29.99)

        print(f"Product: {product.name}")
        print(f"SKU (identifier): {product.sku}")
        print(f"Has auto id field: {hasattr(product, 'id')}")  # False
        print(f"Created at: {product.created_at}")
