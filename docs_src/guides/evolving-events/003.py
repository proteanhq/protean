"""An event that reads legacy payloads leniently.

`OrderPlaced` dropped its `coupon_code` field. Stored payloads still carry it,
and `lenient=True` lets them load without it.
"""

# --8<-- [start:lenient]
from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Identifier, Integer

domain = Domain(name="Ordering")


@domain.aggregate
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


@domain.event(part_of=Order, lenient=True)
class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)
    amount = Integer(required=True)


# --8<-- [end:lenient]
