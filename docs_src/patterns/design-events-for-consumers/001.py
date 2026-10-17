from protean import Domain
from protean.fields import (
    Auto,
    DateTime,
    Float,
    Identifier,
    Integer,
    List,
    String,
)

domain = Domain(name="DeltaEvents")


# --8<-- [start:delta_events]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    customer_email: String(required=True)
    items: List(required=True)
    total: Float(required=True)
    placed_at: DateTime(required=True)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_email: String(required=True)
    tracking_number: String(required=True)
    carrier: String(required=True)
    shipped_at: DateTime(required=True)


@domain.event(part_of=Order)
class OrderItemAdded:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    product_name: String(required=True)
    quantity: Integer(required=True)
    unit_price: Float(required=True)
    new_total: Float(required=True)


# --8<-- [end:delta_events]
