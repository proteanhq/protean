# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Float, HasMany, Integer, List, String

domain = Domain(name="Ordering")


def utc_now():
    return datetime.now(UTC)


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)  # simple
    placed_at: DateTime(default=utc_now)  # simple
    tags: List(content_type=String)  # container
    items = HasMany("LineItem")  # association


@domain.entity(part_of=Order)
class LineItem:
    product_name: String(max_length=100, required=True)
    quantity: Integer(min_value=1, default=1)
    price: Float(min_value=0)


# --8<-- [end:aggregate]
