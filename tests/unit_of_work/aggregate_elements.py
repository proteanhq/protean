from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.repository import BaseRepository
from protean.fields import HasMany, HasOne, Reference


class Post(BaseAggregate):
    title: str
    slug: str
    content: str
    posted_at: datetime = datetime.now()

    meta = HasOne("tests.unit_of_work.aggregate_elements.PostMeta")
    comments = HasMany("tests.unit_of_work.aggregate_elements.Comment")


class PostMeta(BaseEntity):
    likes: int = 0

    post = Reference(Post)


class Comment(BaseEntity):
    content: str
    commented_at: datetime = datetime.now()

    post = Reference(Post)


class PostRepository(BaseRepository):
    pass
