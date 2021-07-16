from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.field.association import HasMany, HasOne, Reference
from protean.core.field.basic import DateTime, Integer, String, Text


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
