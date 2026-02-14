from datetime import datetime, timezone

from protean.domain import Domain
from protean.fields import DateTime, HasMany, HasOne, Integer, Reference, String

publishing = Domain(__name__)


def utc_now():
    return datetime.now(timezone.utc)


@publishing.aggregate
class Post:
    title: String(max_length=50)
    created_at: DateTime(default=utc_now)

    stats = HasOne("Statistic")
    comments = HasMany("Comment")


@publishing.entity(part_of=Post)
class Statistic:
    likes: Integer()
    dislikes: Integer()
    post = Reference(Post)


@publishing.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
    post = Reference(Post)
    added_at: DateTime()
