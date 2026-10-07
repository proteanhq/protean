# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Float, String

domain = Domain(name="Catalogue")


def utc_now():
    return datetime.now(UTC)


@domain.aggregate
class Product:
    name: String(max_length=100, required=True)
    price: Float(min_value=0)
    created_at: DateTime(default=utc_now)


# --8<-- [end:aggregate]
