from datetime import datetime, timezone

from protean import Domain
from protean.fields import DateTime, String

domain = Domain(__file__, load_toml=False)


def utc_now():
    return datetime.now(timezone.utc)


@domain.aggregate(abstract=True)
class TimeStamped:
    created_at = DateTime(default=utc_now)
    updated_at = DateTime(default=utc_now)


@domain.aggregate
class User(TimeStamped):
    name = String(max_length=30)
    timezone = String(max_length=30)
