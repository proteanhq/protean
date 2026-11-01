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
        cache = blog._temp_cache.get("meta")
        assert cache is None or cache.change is None

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
        cache = blog._temp_cache.get("meta")
        assert cache is not None
        assert cache.change == "UPDATED"


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


# ---------------------------------------------------------------------------
# Tests: HasOne.__set__ contract
# ---------------------------------------------------------------------------
class Library(BaseAggregate):
    name: String(max_length=50)
    librarian = HasOne("Librarian")


class Librarian(BaseEntity):
    name: String(max_length=50)
    desk = HasOne("Desk")


class Desk(BaseEntity):
    floor: Integer()


@pytest.fixture
def blog_domain(test_domain):
    test_domain.register(Blog)
    test_domain.register(BlogMeta, part_of=Blog)
    test_domain.register(BlogPost, part_of=Blog)
    test_domain.init(traverse=False)


@pytest.fixture
def library_domain(test_domain):
    test_domain.register(Library)
    test_domain.register(Librarian, part_of=Library)
    test_domain.register(Desk, part_of=Librarian)
    test_domain.init(traverse=False)


class TestHasOneSetContract:
    def test_dict_is_turned_into_the_target_entity(self, blog_domain):
        blog = Blog(title="My Blog")
        blog.meta = {"description": "About blog"}

        assert isinstance(blog.meta, BlogMeta)
        assert blog.meta.description == "About blog"

    def test_first_assignment_is_recorded_as_added_and_linked(self, blog_domain):
        blog = Blog(title="My Blog")
        meta = BlogMeta(description="About blog")
        blog.meta = meta

        assert blog._temp_cache["meta"].change == "ADDED"
        assert meta.blog_id == blog.id

    def test_replacing_the_child_records_updated_with_the_old_child(self, blog_domain):
        old = BlogMeta(description="Old")
        blog = Blog(title="My Blog", meta=old)
        blog.meta = BlogMeta(description="New")

        cache = blog._temp_cache["meta"]
        assert cache.change == "UPDATED"
        assert cache.old_value is old

    def test_assigning_none_records_deleted_with_the_old_child(self, blog_domain):
        old = BlogMeta(description="Old")
        blog = Blog(title="My Blog", meta=old)
        blog.meta = None

        cache = blog._temp_cache["meta"]
        assert cache.change == "DELETED"
        assert cache.old_value is old

    def test_removing_a_child_removes_the_entities_linked_under_it(
        self, library_domain
    ):
        librarian = Librarian(name="Jane", desk=Desk(floor=2))
        library = Library(name="City", librarian=librarian)

        library.librarian = None

        assert librarian.desk is None
        assert librarian._temp_cache["desk"].change == "DELETED"


# ---------------------------------------------------------------------------
# Tests: HasMany.add contract
# ---------------------------------------------------------------------------
class TestHasManyAddContract:
    def test_new_items_are_recorded_as_added_and_linked(self, blog_domain):
        blog = Blog(title="My Blog")
        post = BlogPost(content="Hello")
        blog.add_posts(post)

        assert blog._temp_cache["posts"].added == {post.id: post}
        assert post.blog_id == blog.id

    def test_persisted_changed_items_are_recorded_as_updated(self, blog_domain):
        post = BlogPost(content="Hello")
        blog = Blog(title="My Blog", posts=[post])
        post.state_.mark_retrieved()
        post.content = "Changed"

        blog.add_posts(post)

        assert blog._temp_cache["posts"].updated == {post.id: post}

    def test_empty_list_removes_every_current_child(self, blog_domain):
        first = BlogPost(content="One")
        second = BlogPost(content="Two")
        blog = Blog(title="My Blog", posts=[first, second])

        blog.add_posts([])

        assert blog.posts == []
        assert set(blog._temp_cache["posts"].removed) == {first.id, second.id}

    def test_wrong_type_raises(self, blog_domain):
        blog = Blog(title="My Blog")

        with pytest.raises(ValidationError, match="not of type"):
            blog.add_posts(BlogMeta(description="Wrong type"))
