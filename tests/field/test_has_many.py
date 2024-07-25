import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import HasMany, String
from protean.utils.reflection import attributes, declared_fields


class Post(BaseAggregate):
    content = String()
    comments = HasMany("Comment")


class Comment(BaseEntity):
    content = String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.init(traverse=False)


class TestHasManyFieldInProperties:
    def test_that_has_many_field_appears_in_fields(self):
        assert "comments" in declared_fields(Post)

    def test_that_has_many_field_does_not_appear_in_attributes(self):
        assert "comments" not in attributes(Post)

    def test_that_reference_field_appears_in_fields(self):
        assert "post" in declared_fields(Comment)

    def test_that_reference_field_does_not_appear_in_attributes(self):
        assert "post" not in attributes(Comment)


class TestHasManyField:
    def test_that_has_many_field_cannot_be_linked_to_aggregates(self, test_domain):
        class InvalidAggregate(BaseAggregate):
            post = HasMany(Post)

        test_domain.register(InvalidAggregate)
        with pytest.raises(IncorrectUsageError):
            # The `post` field is invalid because it is linked to another Aggregate
            test_domain._validate_domain()


class TestHasManyPersistence:
    def test_that_has_many_field_is_persisted_along_with_aggregate(self, test_domain):
        comment = Comment(content="First Comment")
        post = Post(content="My Post", comments=[comment])

        test_domain.repository_for(Post).add(post)

        assert post.id is not None
        assert post.comments[0].id is not None

        persisted_post = test_domain.repository_for(Post).get(post.id)
        assert persisted_post.comments[0] == comment
        assert persisted_post.comments[0].id == comment.id
        assert persisted_post.comments[0].content == comment.content

    def test_that_has_many_field_is_persisted_on_aggregate_update(self, test_domain):
        post = Post(content="My Post")
        test_domain.repository_for(Post).add(post)

        assert post.id is not None
        assert len(post.comments) == 0

        comment = Comment(content="First Comment")

        # Fetch the persisted book and update its author
        persisted_post = test_domain.repository_for(Post).get(post.id)
        persisted_post.add_comments(comment)
        test_domain.repository_for(Post).add(persisted_post)

        # Fetch it again to ensure the author is persisted
        persisted_post = test_domain.repository_for(Post).get(post.id)

        # Ensure that the author is persisted along with the book
        assert persisted_post.comments[0] == comment
        assert persisted_post.comments[0].id == comment.id
        assert persisted_post.comments[0].content == comment.content

    def test_that_has_many_field_is_updated_with_new_entity_on_aggregate_update(
        self, test_domain
    ):
        comment = Comment(content="First Comment")
        post = Post(content="My Post", comments=[comment])

        test_domain.repository_for(Post).add(post)

        persisted_post = test_domain.repository_for(Post).get(post.id)

        new_comment = Comment(content="Second Comment")
        persisted_post.add_comments(new_comment)

        test_domain.repository_for(Post).add(persisted_post)

        # Fetch the post again to ensure comments are updated
        updated_book = test_domain.repository_for(Post).get(persisted_post.id)
        assert len(updated_book.comments) == 2
        assert updated_book.comments[0] == comment
        assert updated_book.comments[0].id == comment.id
        assert updated_book.comments[0].content == comment.content
        assert updated_book.comments[1] == new_comment
        assert updated_book.comments[1].id == new_comment.id
        assert updated_book.comments[1].content == new_comment.content

    def test_that_has_many_field_content_can_be_removed_on_aggregate_update(
        self, test_domain
    ):
        comment = Comment(content="First Comment")
        post = Post(content="My Post", comments=[comment])

        test_domain.repository_for(Post).add(post)

        persisted_post = test_domain.repository_for(Post).get(post.id)

        # Remove the author from the book
        persisted_post.remove_comments(comment)

        test_domain.repository_for(Post).add(persisted_post)

        # Fetch the book again to ensure the author is removed
        updated_post = test_domain.repository_for(Post).get(persisted_post.id)
        assert len(updated_post.comments) == 0
