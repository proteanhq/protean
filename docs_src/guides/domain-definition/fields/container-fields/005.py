from protean import Domain

domain = Domain(name="Ordering")


# --8<-- [start:place_order]
from protean.fields import (
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObjectFromEntity,
)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=ValueObjectFromEntity(OrderItem))


# --8<-- [end:place_order]
