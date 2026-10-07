from protean import Domain
from protean.fields import (
    Auto,
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

domain = Domain(name="SmallAggregatesSnapshot")


# --8<-- [start:snapshot]
@domain.value_object
class CustomerSnapshot:
    customer_id: String(required=True)
    name: String(required=True)
    email: String(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer = ValueObject(CustomerSnapshot)  # Snapshot, not the live aggregate
    items = HasMany("OrderItem")
    status: String(default="pending")
    total: Float(default=0.0)


# --8<-- [end:snapshot]


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)
