from datetime import UTC, datetime

from protean import BaseAggregate, BaseEntity, BaseValueObject
from protean.fields import (
    DateTime,
    HasMany,
    HasOne,
    Integer,
    Reference,
    String,
    Text,
    ValueObject,
)
from protean.utils import utcnow_func


class TestAggregateWithNoEnclosedEntitiesOrValueObjects:
    def test_basic_as_dict(self):
        class Post(BaseAggregate):
            title = String(required=True, max_length=1000)
            slug = String(required=True, max_length=1024)
            content = Text(required=True)

        post = Post(title="Test Post", slug="test-post", content="Do Re Mi Fa")

        assert post.to_dict() == {
            "id": post.id,
            "title": "Test Post",
            "slug": "test-post",
            "content": "Do Re Mi Fa",
        }

    def test_as_dict_with_date_fields(self):
        class Post(BaseAggregate):
            title = String(required=True, max_length=1000)
            slug = String(required=True, max_length=1024)
            content = Text(required=True)
            posted_at = DateTime(required=True, default=utcnow_func)

        current_time = datetime.now(UTC)
        post = Post(
            title="Test Post",
            slug="test-post",
            content="Do Re Mi Fa",
            posted_at=current_time,
        )

        assert post.to_dict() == {
            "id": post.id,
            "title": "Test Post",
            "slug": "test-post",
            "content": "Do Re Mi Fa",
            "posted_at": str(current_time),
        }

    def test_as_dict_with_aggregate_that_has_many_entities(self, test_domain):
        class Comment(BaseEntity):
            content = Text(required=True)

            post = Reference("Post")

            class Meta:
                part_of = "Post"

        class Post(BaseAggregate):
            title = String(required=True, max_length=1000)
            slug = String(required=True, max_length=1024)
            content = Text(required=True)

            comments = HasMany(Comment)

        test_domain.register(Post)
        test_domain.register(Comment)

        post = Post(title="Test Post", slug="test-post", content="Do Re Mi Fa")
        comment1 = Comment(content="first comment")
        comment2 = Comment(content="second comment")
        post.add_comments([comment1, comment2])

        assert post.to_dict() == {
            "id": post.id,
            "title": "Test Post",
            "slug": "test-post",
            "content": "Do Re Mi Fa",
            "comments": [
                {"id": comment1.id, "content": "first comment"},
                {"id": comment2.id, "content": "second comment"},
            ],
        }

    def test_as_dict_with_aggregate_that_has_many_entities_with_reference(
        self, test_domain
    ):
        class Comment(BaseEntity):
            content = Text(required=True)
            post = Reference("Post")

            class Meta:
                part_of = "Post"

        class Post(BaseAggregate):
            title = String(required=True, max_length=1000)
            slug = String(required=True, max_length=1024)
            content = Text(required=True)

            comments = HasMany(Comment)

        test_domain.register(Post)
        test_domain.register(Comment)
        test_domain.init(traverse=False)

        post = Post(title="Test Post", slug="test-post", content="Do Re Mi Fa")
        comment1 = Comment(content="first comment", post=post)
        comment2 = Comment(content="second comment", post=post)
        post.add_comments([comment1, comment2])

        assert post.to_dict() == {
            "id": post.id,
            "title": "Test Post",
            "slug": "test-post",
            "content": "Do Re Mi Fa",
            "comments": [
                {"id": comment1.id, "content": "first comment"},
                {"id": comment2.id, "content": "second comment"},
            ],
        }

    def test_as_dict_with_aggregate_that_has_one_entity(self, test_domain):
        class Post(BaseAggregate):
            title = String(required=True, max_length=1000)
            slug = String(required=True, max_length=1024)
            content = Text(required=True)

            meta = HasOne("PostMeta")

        class PostMeta(BaseEntity):
            likes = Integer(default=0)

            class Meta:
                part_of = Post

        test_domain.register(Post)
        test_domain.register(PostMeta)
        test_domain.init(traverse=False)

        meta = PostMeta(likes=27)
        post = Post(
            title="Test Post", slug="test-post", content="Do Re Mi Fa", meta=meta
        )

        assert post.to_dict() == {
            "id": post.id,
            "title": "Test Post",
            "slug": "test-post",
            "content": "Do Re Mi Fa",
            "meta": {"id": meta.id, "likes": 27},
        }

    def test_as_dict_with_aggregate_that_has_a_value_object(self, test_domain):
        class Email(BaseValueObject):
            address = String(max_length=254, required=True)

        class User(BaseAggregate):
            email = ValueObject(Email, required=True)
            password = String(required=True, max_length=255)

        user = User(email=Email(address="john.doe@gmail.com"), password="secret")
        assert user.to_dict() == {
            "id": user.id,
            "email": {
                "address": "john.doe@gmail.com",
            },
            "password": "secret",
        }
