from datetime import datetime, timezone

from protean import Domain

publishing = Domain(name="Publishing")


def utc_now():
    return datetime.now(timezone.utc)


@publishing.command(part_of="Article")
class PublishArticle:
    article_id: str
    published_at: datetime = utc_now


@publishing.aggregate
class Article:
    article_id: str
    published_at: datetime = utc_now
