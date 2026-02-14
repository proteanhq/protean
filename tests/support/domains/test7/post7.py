from datetime import datetime

from protean.fields import HasMany, Reference
from tests.support.domains.test7.publishing7 import domain


@domain.aggregate
class Post:
    title: str | None = None
    created_on: datetime | None = None

    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: str | None = None
    post = Reference(Post)
