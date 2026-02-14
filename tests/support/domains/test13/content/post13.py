from datetime import datetime

from protean.fields import HasMany, Reference
from tests.support.domains.test13.publishing13 import domain


@domain.aggregate
class Post:
    title: str | None = None
    created_on: datetime = datetime.now

    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: str | None = None
    post = Reference(Post)
