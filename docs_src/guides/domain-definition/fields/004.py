# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, String

domain = Domain(name="Shopping")


def _utc_now():
    return datetime.now(UTC)


@domain.aggregate
class ShoppingCart:
    created_at: DateTime(default=_utc_now)
    currency: String(default="USD")


# --8<-- [end:aggregate]
