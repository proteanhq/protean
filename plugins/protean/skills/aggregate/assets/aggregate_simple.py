"""
Simple aggregate with basic fields.

This example demonstrates:
- Basic aggregate definition with @domain.aggregate decorator
- Simple field types (String, Date, Integer)
- Automatic ID field generation
- Field options (required, max_length, default)

Usage:
    from protean import Domain
    domain = Domain()

    post = Post(title="My First Post", status="draft")
    domain.repository_for(Post).add(post)
"""

from datetime import date

from protean import Domain
from protean.fields import Date, Integer, String

# Domain setup (required for runnable examples)
domain = Domain()


@domain.aggregate
class Post:
    """A blog post aggregate with basic fields."""

    title: String(required=True, max_length=200)
    content: String(max_length=5000)
    status: String(max_length=20, default="draft")
    published_on: Date()
    view_count: Integer(default=0)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a new post
        post = Post(
            title="Getting Started with Protean",
            content="Protean is a DDD framework...",
            status="draft",
            published_on=date.today(),
        )

        print(f"Created post: {post.title}")
        print(f"Status: {post.status}")
        print(f"ID: {post.id}")  # Auto-generated
        print(f"View count: {post.view_count}")  # Default value
