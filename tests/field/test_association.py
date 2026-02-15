"""Tests for Association descriptors in fields/association.py."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import NotSupportedError, ValidationError
from protean.fields import HasMany, HasOne, Integer, Reference, String


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Blog(BaseAggregate):
    title: String(required=True, max_length=100)
    meta = HasOne("BlogMeta")
    posts = HasMany("BlogPost")


class BlogMeta(BaseEntity):
    description: String(max_length=500)
    blog = Reference(Blog)


class BlogPost(BaseEntity):
    content: String(required=True, max_length=1000)
    likes: Integer(default=0)
    blog = Reference(Blog)


# ---------------------------------------------------------------------------
# Tests: Association.__delete__
# ---------------------------------------------------------------------------
class TestAssociationDelete:
    def test_delete_association_raises_not_supported(self, test_domain):
        """Deleting an association raises NotSupportedError."""
        test_domain.register(Blog)
        test_domain.register(BlogMeta, part_of=Blog)
        test_domain.register(BlogPost, part_of=Blog)
        test_domain.init(traverse=False)

        blog = Blog(title="My Blog")
        with pytest.raises(NotSupportedError):
            del blog.meta


# ---------------------------------------------------------------------------
# Tests: Association.has_changed and _clone
# ---------------------------------------------------------------------------
class TestAssociationProperties:
    def test_has_changed_property(self):
        """has_changed reflects change attribute."""
        assoc = HasOne("SomeEntity")
        assoc.change = None
        assert assoc.has_changed is False
        assoc.change = "ADDED"
        assert assoc.has_changed is True

    def test_clone_returns_self(self):
        """Association._clone() returns self."""
        assoc = HasOne("SomeEntity")
        cloned = assoc._clone()
        assert cloned is assoc


# ---------------------------------------------------------------------------
# Tests: HasOne __set__ update and no-op branches
# ---------------------------------------------------------------------------
class TestHasOneSetEdgeCases:
    def test_has_one_set_same_entity_no_change(self, test_domain):
        """Assigning same unchanged entity is a No-Op."""
        test_domain.register(Blog)
        test_domain.register(BlogMeta, part_of=Blog)
        test_domain.register(BlogPost, part_of=Blog)
        test_domain.init(traverse=False)

        meta = BlogMeta(description="About blog")
        blog = Blog(title="My Blog", meta=meta)

        # Re-assign same entity (no state change) -> No-Op
        blog.meta = meta
        cache = blog._temp_cache.get("meta", {})
        assert cache.get("change") is None

    def test_has_one_set_updated_entity(self, test_domain):
        """Assigning same entity with changed state -> UPDATED."""
        test_domain.register(Blog)
        test_domain.register(BlogMeta, part_of=Blog)
        test_domain.register(BlogPost, part_of=Blog)
        test_domain.init(traverse=False)

        meta = BlogMeta(description="About blog")
        blog = Blog(title="My Blog", meta=meta)

        # Simulate: mark as retrieved (not new), then mark as changed
        meta.state_.mark_retrieved()
        meta.state_.mark_changed()
        assert meta.state_.is_changed is True

        blog.meta = meta
        cache = blog._temp_cache.get("meta", {})
        assert cache.get("change") == "UPDATED"


# ---------------------------------------------------------------------------
# Tests: HasMany.remove with wrong type
# ---------------------------------------------------------------------------
class TestHasManyRemoveEdgeCases:
    def test_remove_wrong_type_raises(self, test_domain):
        """Removing item of wrong type raises ValidationError."""
        test_domain.register(Blog)
        test_domain.register(BlogMeta, part_of=Blog)
        test_domain.register(BlogPost, part_of=Blog)
        test_domain.init(traverse=False)

        blog = Blog(title="My Blog")
        post = BlogPost(content="Hello world")
        blog.add_posts(post)

        # Try removing a non-BlogPost object
        with pytest.raises(ValidationError, match="not of type"):
            blog.remove_posts(BlogMeta(description="Wrong type"))
