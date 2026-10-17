# --8<-- [start:shared_kernel]
# shared_kernel/events.py -- intentionally shared
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier, List


class OrderPlacedEvent(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


# --8<-- [end:shared_kernel]
