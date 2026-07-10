# --8<-- [start:full]
from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, String

domain = Domain()


@domain.aggregate
class Post:
    title: String(max_length=255)
    created_at: DateTime(default=lambda: datetime.now(UTC))


# --8<-- [end:full]
