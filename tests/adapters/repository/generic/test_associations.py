"""Generic HasMany association tests that run against all database providers.

Covers child entity persistence, update, and removal through the parent
aggregate's repository.
"""

from datetime import UTC, datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import DateTime, HasMany, Reference, String, Text


class Comment(BaseEntity):
    content: Text()
    added_on: DateTime()

    post = Reference("Post")


class Post(BaseAggregate):
    title: String(max_length=255, required=True)
    body: Text()
    comments = HasMany(Comment)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestHasManyPersistence:
    """Persist aggregates with child entities and verify retrieval."""

    def test_persist_aggregate_with_child_entities(self, test_domain):
        post = Post(title="Hello World", body="First post")
        post.add_comments(Comment(content="Great post!", added_on=datetime.now(UTC)))
        post.add_comments(Comment(content="Thanks!", added_on=datetime.now(UTC)))
        test_domain.repository_for(Post).add(post)

        retrieved = test_domain.repository_for(Post).get(post.id)
        assert retrieved.title == "Hello World"
        assert len(retrieved.comments) == 2

        comment_contents = {c.content for c in retrieved.comments}
        assert comment_contents == {"Great post!", "Thanks!"}

    def test_persist_aggregate_with_no_children(self, test_domain):
        post = Post(title="Empty Post", body="No comments yet")
        test_domain.repository_for(Post).add(post)

        retrieved = test_domain.repository_for(Post).get(post.id)
        assert retrieved.title == "Empty Post"
        assert len(retrieved.comments) == 0

    def test_child_entity_attributes_round_trip(self, test_domain):
        now = datetime.now(UTC)
        post = Post(title="Detailed Post", body="With timestamps")
        post.add_comments(Comment(content="Timed comment", added_on=now))
        test_domain.repository_for(Post).add(post)

        retrieved = test_domain.repository_for(Post).get(post.id)
        comment = retrieved.comments[0]
        assert comment.content == "Timed comment"
        assert comment.added_on is not None


@pytest.mark.basic_storage
class TestHasManyUpdate:
    """Add and update child entities on existing aggregates."""

    def test_add_child_to_existing_aggregate(self, test_domain):
        post = Post(title="Growing Post", body="Will get comments")
        test_domain.repository_for(Post).add(post)

        # Retrieve, add a child, re-persist
        retrieved = test_domain.repository_for(Post).get(post.id)
        retrieved.add_comments(
            Comment(content="Late comment", added_on=datetime.now(UTC))
        )
        test_domain.repository_for(Post).add(retrieved)

        updated = test_domain.repository_for(Post).get(post.id)
        assert len(updated.comments) == 1
        assert updated.comments[0].content == "Late comment"

    def test_add_multiple_children_incrementally(self, test_domain):
        post = Post(title="Incremental Post", body="Step by step")
        post.add_comments(Comment(content="First", added_on=datetime.now(UTC)))
        test_domain.repository_for(Post).add(post)

        # Add a second comment
        retrieved = test_domain.repository_for(Post).get(post.id)
        retrieved.add_comments(Comment(content="Second", added_on=datetime.now(UTC)))
        test_domain.repository_for(Post).add(retrieved)

        updated = test_domain.repository_for(Post).get(post.id)
        assert len(updated.comments) == 2

    def test_update_existing_child_attributes(self, test_domain):
        post = Post(title="Editable Post", body="With editable comments")
        post.add_comments(Comment(content="Original", added_on=datetime.now(UTC)))
        test_domain.repository_for(Post).add(post)

        # Retrieve, modify child, re-persist via parent
        retrieved = test_domain.repository_for(Post).get(post.id)
        comment = retrieved.comments[0]
        comment.content = "Edited"
        retrieved.add_comments(comment)
        test_domain.repository_for(Post).add(retrieved)

        updated = test_domain.repository_for(Post).get(post.id)
        assert len(updated.comments) == 1
        assert updated.comments[0].content == "Edited"


@pytest.mark.basic_storage
class TestHasManyRemoval:
    """Remove child entities from aggregates."""

    def test_remove_single_child(self, test_domain):
        post = Post(title="Shrinking Post", body="Will lose a comment")
        comment = Comment(content="Doomed comment", added_on=datetime.now(UTC))
        post.add_comments(comment)
        test_domain.repository_for(Post).add(post)

        # Retrieve and remove the child
        retrieved = test_domain.repository_for(Post).get(post.id)
        retrieved.remove_comments(retrieved.comments[0])
        test_domain.repository_for(Post).add(retrieved)

        updated = test_domain.repository_for(Post).get(post.id)
        assert len(updated.comments) == 0

    def test_remove_one_child_from_many(self, test_domain):
        post = Post(title="Selective Post", body="Remove one of two")
        comment1 = Comment(content="Keep me", added_on=datetime.now(UTC))
        comment2 = Comment(content="Remove me", added_on=datetime.now(UTC))
        post.add_comments(comment1)
        post.add_comments(comment2)
        test_domain.repository_for(Post).add(post)

        # Remove only one child
        retrieved = test_domain.repository_for(Post).get(post.id)
        to_remove = next(c for c in retrieved.comments if c.content == "Remove me")
        retrieved.remove_comments(to_remove)
        test_domain.repository_for(Post).add(retrieved)

        updated = test_domain.repository_for(Post).get(post.id)
        assert len(updated.comments) == 1
        assert updated.comments[0].content == "Keep me"
