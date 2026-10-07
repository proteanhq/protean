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

domain = Domain(name="SmallAggregatesValueObjects")


# --8<-- [start:value_objects]
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)


@domain.value_object
class ShippingAddress:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    total = ValueObject(Money)
    shipping_address = ValueObject(ShippingAddress)  # Snapshot at order time


# --8<-- [end:value_objects]


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)
