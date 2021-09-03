from datetime import datetime

from protean import BaseAggregate, BaseEntity
from protean.fields import DateTime, HasMany, HasOne, Integer, Reference, String, Text


class Post(BaseAggregate):
    title = String(required=True, max_length=1000)
    slug = String(required=True, max_length=1024)
    content = Text(required=True)
    posted_at = DateTime(required=True, default=datetime.now())

    post_meta = HasOne("tests.repository.child_entities.PostMeta")
    comments = HasMany("tests.repository.child_entities.Comment")


class PostMeta(BaseEntity):
    likes = Integer(default=0)

    post = Reference(Post)

    class Meta:
        aggregate_cls = Post


class Comment(BaseEntity):
    content = Text(required=True)
    commented_at = DateTime(required=True, default=datetime.now())

    post = Reference(Post)

    class Meta:
        aggregate_cls = Post
