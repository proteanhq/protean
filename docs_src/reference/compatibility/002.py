# --8<-- [start:setup]
from protean import Domain
from protean.core.event import BaseEvent
from protean.fields import Identifier

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderPlacedV2(BaseEvent):
    order_id: Identifier(required=True)


# --8<-- [end:setup]


# --8<-- [start:superseded_by]
@domain.event(
    part_of=Order,
    deprecated={"since": "0.16", "removal": "0.19"},
    superseded_by=OrderPlacedV2,
)
class OrderPlaced(BaseEvent): ...


# --8<-- [end:superseded_by]
