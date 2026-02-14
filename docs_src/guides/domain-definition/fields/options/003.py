from datetime import datetime, timezone

from protean.domain import Domain
from protean.fields import DateTime, String

publishing = Domain(__name__)


def utc_now():
    return datetime.now(timezone.utc)


@publishing.aggregate
class Post:
    title: String(max_length=50)
    created_at: DateTime(default=utc_now)
