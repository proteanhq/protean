from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier

domain = Domain(name="Ordering")


@domain.aggregate
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


# --8<-- [start:before]
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    amount = Float(required=True)


# --8<-- [end:before]
