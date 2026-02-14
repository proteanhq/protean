from datetime import datetime, timezone

from protean import Domain
from protean.fields import DateTime, String

domain = Domain()


@domain.aggregate
class Post:
    title: String(max_length=255)
    created_at: DateTime(default=lambda: datetime.now(timezone.utc))
