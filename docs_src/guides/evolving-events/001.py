"""The Ordering domain at its original v1 shape.

This is the baseline the rest of the "Evolving events over time" guide evolves
away from. `OrderPlaced` is at its implicit version 1.
"""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Identifier, Integer, String

domain = Domain(name="Ordering")


@domain.aggregate
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)
    amount = Integer(required=True)
    customer_name = String(required=True)
