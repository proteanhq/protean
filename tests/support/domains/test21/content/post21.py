from datetime import datetime

from protean.fields import HasMany, Reference

from ..publishing21 import publishing


@publishing.aggregate
class Post:
    title: str | None = None
    created_on: datetime | None = None

    comments = HasMany("Comment")


@publishing.entity(part_of=Post)
class Comment:
    content: str | None = None
    post = Reference(Post)
