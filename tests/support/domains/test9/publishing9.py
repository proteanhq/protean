"""A simple dummy domain module with domain elements in the same file"""

from datetime import datetime

from protean.domain import Domain
from protean.fields import HasMany, Reference

domain = Domain(name="TEST9")


@domain.aggregate
class Post:
    title: str | None = None
    created_on: datetime | None = None

    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: str | None = None
    post = Reference(Post)
