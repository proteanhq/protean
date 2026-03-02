"""Tests for eager pre-warming of association fields on repository.get() and find_by().

In DDD, loading an aggregate should return the complete aggregate boundary.
After G2, ``get()`` and ``find_by()`` explicitly pre-warm all HasMany/HasOne
field caches so that callers receive a fully-formed aggregate without
triggering lazy loads.
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate

from .child_entities import Comment, Post, PostMeta


# ---------------------------------------------------------------------------
# Simple aggregate without associations (for negative test)
# ---------------------------------------------------------------------------
class Person(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: str


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(PostMeta, part_of=Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.register(Person)
    test_domain.init(traverse=False)


@pytest.fixture()
def persisted_post_with_children(test_domain):
    """Create and persist a Post with both HasOne (PostMeta) and HasMany (Comments)."""
    post = Post(
        title="Test Post",
        slug="test-post",
        content="Hello World",
    )
    post.post_meta = PostMeta(likes=42)
    post.comments = [
        Comment(content="First comment"),
        Comment(content="Second comment"),
    ]
    test_domain.repository_for(Post).add(post)
    return post


@pytest.fixture()
def persisted_post_without_children(test_domain):
    """Create and persist a Post with no children."""
    post = Post(
        title="Bare Post",
        slug="bare-post",
        content="No children here",
    )
    test_domain.repository_for(Post).add(post)
    return post


# ---------------------------------------------------------------------------
# Tests: Pre-warm on get()
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestPrewarmOnGet:
    def test_has_many_prewarmed_after_get(
        self, test_domain, persisted_post_with_children
    ):
        """HasMany children should be in the field cache immediately after get()."""
        post = test_domain.repository_for(Post).get(persisted_post_with_children.id)

        # The association field cache should already be populated
        comments_field = Post.__dict__["comments"]
        assert comments_field.is_cached(post)

        # And the data should be correct
        assert len(post.comments) == 2
        contents = {c.content for c in post.comments}
        assert contents == {"First comment", "Second comment"}

    def test_has_one_prewarmed_after_get(
        self, test_domain, persisted_post_with_children
    ):
        """HasOne child should be in the field cache immediately after get()."""
        post = test_domain.repository_for(Post).get(persisted_post_with_children.id)

        post_meta_field = Post.__dict__["post_meta"]
        assert post_meta_field.is_cached(post)

        assert post.post_meta is not None
        assert post.post_meta.likes == 42

    def test_both_associations_prewarmed(
        self, test_domain, persisted_post_with_children
    ):
        """Both HasMany and HasOne should be pre-warmed together."""
        post = test_domain.repository_for(Post).get(persisted_post_with_children.id)

        comments_field = Post.__dict__["comments"]
        post_meta_field = Post.__dict__["post_meta"]

        assert comments_field.is_cached(post)
        assert post_meta_field.is_cached(post)

    def test_aggregate_without_associations_works(self, test_domain):
        """get() on an aggregate with no association fields should not error."""
        person = Person(name="Alice")
        test_domain.repository_for(Person).add(person)

        retrieved = test_domain.repository_for(Person).get(person.id)
        assert retrieved.name == "Alice"

    def test_prewarmed_has_many_children_not_marked_changed(
        self, test_domain, persisted_post_with_children
    ):
        """Pre-warmed HasMany children should not appear dirty."""
        post = test_domain.repository_for(Post).get(persisted_post_with_children.id)

        for comment in post.comments:
            assert not comment.state_.is_changed
            assert comment.state_.is_persisted

    def test_no_children_still_caches_empty(
        self, test_domain, persisted_post_without_children
    ):
        """Aggregates with association fields but no children should still
        pre-warm (caching empty list / None)."""
        post = test_domain.repository_for(Post).get(persisted_post_without_children.id)

        comments_field = Post.__dict__["comments"]
        post_meta_field = Post.__dict__["post_meta"]

        assert comments_field.is_cached(post)
        assert post_meta_field.is_cached(post)

        assert post.comments == []
        assert post.post_meta is None

    def test_children_data_matches_persisted(
        self, test_domain, persisted_post_with_children
    ):
        """Pre-warmed children should have correct data values."""
        post = test_domain.repository_for(Post).get(persisted_post_with_children.id)

        # Verify HasMany data
        assert len(post.comments) == 2
        comment_contents = sorted(c.content for c in post.comments)
        assert comment_contents == ["First comment", "Second comment"]

        # Verify HasOne data
        assert post.post_meta.likes == 42


# ---------------------------------------------------------------------------
# Tests: Pre-warm on find_by()
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestPrewarmOnFindBy:
    def test_find_by_prewarms_associations(
        self, test_domain, persisted_post_with_children
    ):
        """find_by() should pre-warm associations just like get()."""
        post = test_domain.repository_for(Post).find_by(slug="test-post")

        comments_field = Post.__dict__["comments"]
        post_meta_field = Post.__dict__["post_meta"]

        assert comments_field.is_cached(post)
        assert post_meta_field.is_cached(post)

        assert len(post.comments) == 2
        assert post.post_meta is not None
        assert post.post_meta.likes == 42

    def test_find_by_no_children(self, test_domain, persisted_post_without_children):
        """find_by() should pre-warm even when no children exist."""
        post = test_domain.repository_for(Post).find_by(slug="bare-post")

        comments_field = Post.__dict__["comments"]
        assert comments_field.is_cached(post)
        assert post.comments == []
