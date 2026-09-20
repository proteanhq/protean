"""
Simple entity with basic fields.

This example demonstrates:
- Basic entity definition with @domain.entity decorator
- Required part_of parameter to associate with aggregate
- Simple field types (String, Integer, Float)
- Automatic id field generation
- Automatic reference field to parent aggregate
- Entity methods and computed properties

Usage:
    post = Post(title="My Post")
    comment = Comment(content="Great post!", author="John")
    post.add_comments([comment])
    domain.repository_for(Post).add(post)
"""

from protean import Domain
from protean.fields import HasMany, Integer, String, Text

# Domain setup
domain = Domain()


@domain.aggregate
class Post:
    """A blog post aggregate that contains comments."""

    title: String(required=True, max_length=200)
    content: Text()
    status: String(max_length=20, default="draft")

    # One-to-many relationship: a post has many comments
    comments = HasMany("Comment")

    @property
    def comment_count(self) -> int:
        """Get the number of comments."""
        return len(self.comments) if self.comments else 0

    def publish(self):
        """Publish the post."""
        self.status = "published"


@domain.entity(part_of="Post")
class Comment:
    """A comment entity that belongs to a post."""

    content: String(required=True, max_length=500, min_length=1)
    author: String(required=True, max_length=100, min_length=1)
    upvotes: Integer(default=0, min_value=0)  # Field-level validation

    # Automatic fields added by Protean:
    # - id: Auto-generated identifier
    # - post: Reference(Post) - reference back to parent
    # - post_id: String() - shadow field for parent ID

    def upvote(self):
        """Increment the upvote count."""
        self.upvotes += 1

    @property
    def is_popular(self) -> bool:
        """Check if comment has many upvotes."""
        return self.upvotes >= 10


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a post
        post = Post(
            title="Introduction to Domain-Driven Design",
            content="DDD is a software development approach...",
        )

        # Create comments
        comment1 = Comment(
            content="Great introduction! Very helpful.",
            author="Alice",
        )
        comment2 = Comment(
            content="Looking forward to the next part.",
            author="Bob",
            upvotes=15,
        )

        # Add comments to post
        post.add_comments([comment1, comment2])

        print(f"Post: {post.title}")
        print(f"Comments: {post.comment_count}")

        # Access entities
        for comment in post.comments:
            print(f"  - {comment.author}: {comment.content}")
            print(f"    Upvotes: {comment.upvotes}, Popular: {comment.is_popular}")

        # Demonstrate bidirectional reference
        print(f"\nFirst comment's post: {comment1.post.title}")
        print(f"First comment's post ID: {comment1.post_id}")

        # Upvote a comment
        comment1.upvote()
        print(f"\nAfter upvote: {comment1.upvotes} upvotes")

        # Publish the post
        post.publish()
        print(f"Post status: {post.status}")
