from datetime import UTC, datetime

# --8<-- [start:import_f]
from protean import F

# --8<-- [end:import_f]
# isort: split

from protean import Domain
from protean.fields import DateTime, Integer, String

domain = Domain()


# --8<-- [start:article]
@domain.aggregate
class Article:
    title: String(max_length=100)
    archived_at: DateTime()


# --8<-- [end:article]


# --8<-- [start:notification]
@domain.aggregate
class Notification:
    retry_count: Integer(default=0)
    max_retries: Integer(default=3)


# --8<-- [end:notification]


domain.init(traverse=False)
context = domain.domain_context()
context.push()

domain.repository_for(Article).add(Article(title="Draft"))
domain.repository_for(Article).add(
    Article(title="Old news", archived_at=datetime(2024, 1, 1, tzinfo=UTC))
)
domain.repository_for(Notification).add(Notification(retry_count=1, max_retries=3))
domain.repository_for(Notification).add(Notification(retry_count=3, max_retries=3))
domain.repository_for(Notification).add(Notification(retry_count=4, max_retries=5))
domain.repository_for(Notification).add(Notification(retry_count=2, max_retries=1))

# --8<-- [start:isnull]
articles = domain.repository_for(Article)

# Aggregates whose `archived_at` timestamp has never been set
never_archived = articles.query.filter(archived_at__isnull=True).all().items

# Aggregates that have been archived
archived = articles.query.filter(archived_at__isnull=False).all().items
# --8<-- [end:isnull]

# --8<-- [start:field_reference]
notifications = domain.repository_for(Notification)

# Notifications that still have retries left (retry_count < max_retries)
retrying = notifications.query.filter(retry_count__lt=F("max_retries")).all().items
# --8<-- [end:field_reference]

context.pop()
