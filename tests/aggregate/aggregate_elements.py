from datetime import datetime

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, HasOne, Reference


class Post(BaseAggregate):
    title: str
    slug: str
    content: str
    posted_at: datetime = Field(default_factory=datetime.now)

    meta = HasOne("tests.aggregate.aggregate_elements.PostMeta")
    comments = HasMany("tests.aggregate.aggregate_elements.Comment")


class PostMeta(BaseEntity):
    likes: int = 0

    post = Reference(Post)


class Comment(BaseEntity):
    content: str
    commented_at: datetime = Field(default_factory=datetime.now)

    post = Reference(Post)
