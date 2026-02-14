from datetime import datetime, timezone

from protean.domain import Domain
from protean.fields import HasMany, HasOne, Reference
from typing import Annotated
from pydantic import Field

publishing = Domain(__name__)


def utc_now():
    return datetime.now(timezone.utc)


@publishing.aggregate
class Post:
    title: Annotated[str, Field(max_length=50)] | None = None
    created_at: datetime = utc_now

    stats = HasOne("Statistic")
    comments = HasMany("Comment")


@publishing.entity(part_of=Post)
class Statistic:
    likes: int | None = None
    dislikes: int | None = None
    post = Reference(Post)


@publishing.entity(part_of=Post)
class Comment:
    content: Annotated[str, Field(max_length=500)] | None = None
    post = Reference(Post)
    added_at: datetime | None = None
