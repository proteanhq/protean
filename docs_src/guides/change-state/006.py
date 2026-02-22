from datetime import datetime, timezone

from protean import Domain
from protean.fields import DateTime, Identifier

publishing = Domain(name="Publishing")


def utc_now():
    return datetime.now(timezone.utc)


@publishing.command(part_of="Article")
class PublishArticle:
    article_id: Identifier(required=True)
    published_at: DateTime(default=utc_now)


@publishing.aggregate
class Article:
    article_id: Identifier(required=True)
    published_at: DateTime(default=utc_now)
