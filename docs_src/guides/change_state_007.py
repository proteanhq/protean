from datetime import datetime, timezone
from enum import Enum

from protean import Domain, handle
from protean.fields import DateTime, Identifier, String
from protean.utils.globals import current_domain

publishing = Domain(__file__, "Publishing")


def utc_now():
    return datetime.now(timezone.utc)


class ArticleStatus(Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


@publishing.command(part_of="Article")
class PublishArticle:
    article_id = Identifier(required=True)
    published_at = DateTime(default=utc_now)


@publishing.event(part_of="Article")
class ArticlePublished:
    article_id = Identifier(required=True)
    published_at = DateTime()


@publishing.aggregate
class Article:
    article_id = Identifier(required=True)
    status = String(choices=ArticleStatus, default=ArticleStatus.DRAFT.value)
    published_at = DateTime(default=utc_now)

    def publish(self, published_at: DateTime) -> None:
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
