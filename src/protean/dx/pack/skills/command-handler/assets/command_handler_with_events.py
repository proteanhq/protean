"""
Command handler where the aggregate raises domain events during mutation.

This example demonstrates:
- Full command -> handler -> aggregate mutation -> event raised flow
- Aggregate's raise_() method emitting events during state changes
- Events are persisted alongside the aggregate within the UnitOfWork
- Accessing raised events via aggregate._events

Usage:
    command = PublishArticle(
        article_id="ART-001",
        published_at=datetime.now(UTC),
    )
    domain.process(command, asynchronous=False)
"""

from datetime import UTC, datetime
from enum import Enum

from protean import Domain, handle
from protean.fields import DateTime, Identifier, String, Text

# Domain setup
domain = Domain()


class ArticleStatus(Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


@domain.event(part_of="Article")
class ArticlePublished:
    """Event raised when an article is published."""

    article_id: Identifier(required=True)
    title: String(required=True)
    published_at: DateTime(required=True)


@domain.event(part_of="Article")
class ArticleArchived:
    """Event raised when an article is archived."""

    article_id: Identifier(required=True)
    archived_at: DateTime(required=True)
    reason: String()


@domain.aggregate
class Article:
    """Article aggregate that raises events on state changes."""

    article_id: Identifier(identifier=True)
    title: String(required=True)
    body: Text()
    status: String(choices=ArticleStatus, default=ArticleStatus.DRAFT.value)
    published_at: DateTime()
    archived_at: DateTime()

    def publish(self, published_at: datetime):
        """Publish the article, raising ArticlePublished event."""
        if self.status != ArticleStatus.DRAFT.value:
            raise ValueError(f"Cannot publish article in '{self.status}' status")

        # 1. Mutate state
        self.status = ArticleStatus.PUBLISHED.value
        self.published_at = published_at

        # 2. Raise event AFTER state change
        self.raise_(
            ArticlePublished(
                article_id=self.article_id,
                title=self.title,
                published_at=published_at,
            )
        )

    def archive(self, reason: str = None):
        """Archive the article, raising ArticleArchived event."""
        if self.status != ArticleStatus.PUBLISHED.value:
            raise ValueError(f"Cannot archive article in '{self.status}' status")

        archived_at = datetime.now(UTC)
        self.status = ArticleStatus.ARCHIVED.value
        self.archived_at = archived_at

        self.raise_(
            ArticleArchived(
                article_id=self.article_id,
                archived_at=archived_at,
                reason=reason,
            )
        )


@domain.command(part_of="Article")
class PublishArticle:
    """Command to publish a draft article."""

    article_id: Identifier(required=True)
    published_at: DateTime()


@domain.command(part_of="Article")
class ArchiveArticle:
    """Command to archive a published article."""

    article_id: Identifier(required=True)
    reason: String()


@domain.command_handler(part_of=Article)
class ArticleCommandHandler:
    """Handler for article commands.

    When the aggregate raises events during mutation (e.g., Article.publish()
    calls self.raise_(ArticlePublished(...))), those events are persisted
    alongside the aggregate within the implicit UnitOfWork.
    """

    @handle(PublishArticle)
    def handle_publish(self, command: PublishArticle):
        """Handle PublishArticle command.

        Loads the article, publishes it (which raises ArticlePublished),
        and persists the aggregate along with its events.
        """
        article = domain.repository_for(Article).get(command.article_id)
        published_at = command.published_at or datetime.now(UTC)
        article.publish(published_at=published_at)
        domain.repository_for(Article).add(article)

    @handle(ArchiveArticle)
    def handle_archive(self, command: ArchiveArticle):
        """Handle ArchiveArticle command.

        Loads the article, archives it (which raises ArticleArchived),
        and persists the aggregate along with its events.
        """
        article = domain.repository_for(Article).get(command.article_id)
        article.archive(reason=command.reason)
        domain.repository_for(Article).add(article)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an article directly (in real code, this would be via a command)
        article = Article(
            article_id="ART-001",
            title="Introduction to DDD",
            body="Domain-Driven Design is an approach...",
        )
        domain.repository_for(Article).add(article)
        print(f"Created article: {article.article_id} (status: {article.status})")

        # Publish the article via command
        publish_cmd = PublishArticle(
            article_id="ART-001",
            published_at=datetime.now(UTC),
        )
        domain.process(publish_cmd, asynchronous=False)
        print("Article published")

        # Retrieve and verify
        published_article = domain.repository_for(Article).get("ART-001")
        print(f"Article status: {published_article.status}")
