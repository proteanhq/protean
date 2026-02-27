"""Tests for HasOne state tracking during repository sync.

Fix #2 from audit: When a HasOne child is re-assigned after modification
(same identity), the repository must persist the update even if the
entity's is_changed flag has been cleared between __set__ and sync.
"""

import pytest

from protean.utils.globals import current_domain

from .child_entities import Post, PostMeta, Comment


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(PostMeta, part_of=Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.init(traverse=False)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestHasOneUpdateStateTracking:
    @pytest.fixture
    def post_with_meta(self, test_domain):
        """Create a post with a HasOne PostMeta child, persisted."""
        post = Post(title="Test", slug="test", content="Hello")
        post.post_meta = PostMeta(likes=10)
        return test_domain.repository_for(Post).add(post)

    def test_update_same_has_one_child_persists_changes(
        self, test_domain, post_with_meta
    ):
        """When a HasOne child is modified and re-assigned (same ID),
        the change must be persisted even if state tracking resets."""
        post_repo = current_domain.repository_for(Post)

        # Load, modify the child, and re-assign to trigger HasOne "UPDATED"
        post = post_repo.get(post_with_meta.id)
        meta = post.post_meta
        meta.likes = 42
        post.post_meta = meta  # Same identity, modified attributes

        post_repo.add(post)

        # Verify the update was persisted
        refreshed = post_repo.get(post_with_meta.id)
        assert refreshed.post_meta is not None
        assert refreshed.post_meta.likes == 42

    def test_replace_has_one_child_with_new_instance(self, test_domain, post_with_meta):
        """Replacing a HasOne child with a different instance (new ID)
        should delete the old and persist the new."""
        post_repo = current_domain.repository_for(Post)

        post = post_repo.get(post_with_meta.id)
        old_meta_id = post.post_meta.id

        # Replace with a completely new instance
        post.post_meta = PostMeta(likes=99)
        post_repo.add(post)

        refreshed = post_repo.get(post_with_meta.id)
        assert refreshed.post_meta is not None
        assert refreshed.post_meta.likes == 99
        assert refreshed.post_meta.id != old_meta_id

    def test_direct_child_mutation_without_reassignment(
        self, test_domain, post_with_meta
    ):
        """When a HasOne child is modified directly (without reassignment),
        the change should still be detected via is_changed and persisted."""
        post_repo = current_domain.repository_for(Post)

        post = post_repo.get(post_with_meta.id)
        post.post_meta.likes = 77
        assert post.post_meta.state_.is_changed

        post_repo.add(post)

        refreshed = post_repo.get(post_with_meta.id)
        assert refreshed.post_meta.likes == 77
