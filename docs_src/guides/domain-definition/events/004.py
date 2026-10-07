from protean import Domain
from protean.fields import DateTime, Identifier, String

domain = Domain(name="Ordering")


# --8<-- [start:events]
@domain.aggregate
class Order:
    customer_name = String(max_length=100)


@domain.event(abstract=True)
class BaseOrderEvent:
    order_id = Identifier(required=True)
    occurred_at = DateTime(required=True)


@domain.event(part_of=Order)
class OrderPlaced(BaseOrderEvent):
    customer_name = String(max_length=100)


@domain.event(part_of=Order)
class OrderCancelled(BaseOrderEvent):
    reason = String(max_length=500)


# --8<-- [end:events]
