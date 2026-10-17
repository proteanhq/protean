from protean import Domain
from protean.fields import Auto, Float, Identifier, List

domain = Domain(name="OrderEventsBefore")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:before]
# Before: original event
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


# --8<-- [end:before]
