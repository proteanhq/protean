from datetime import datetime, timezone
from enum import Enum

from protean import Domain, handle
from protean.utils.globals import current_domain

publishing = Domain(name="Publishing")


def utc_now():
    return datetime.now(timezone.utc)


class ArticleStatus(Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


@publishing.command(part_of="Article")
class PublishArticle:
    article_id: str
    published_at: datetime = utc_now


@publishing.event(part_of="Article")
class ArticlePublished:
    article_id: str
    published_at: datetime | None = None


@publishing.aggregate
class Article:
    article_id: str
    status: ArticleStatus = ArticleStatus.DRAFT.value
    published_at: datetime = utc_now

    def publish(self, published_at: datetime) -> None:
        self.status = ArticleStatus.PUBLISHED.value
        self.published_at = published_at

        self.raise_(
            ArticlePublished(article_id=self.article_id, published_at=published_at)
        )


@publishing.command_handler(part_of=Article)
class ArticleCommandHandler:
    @handle(PublishArticle)
    def publish_article(self, command):
        article = current_domain.repository_for(Article).get(command.article_id)
        article.publish()
        current_domain.repository_for(Article).add(article)
