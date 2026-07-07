"""The Ordering domain after evolving `OrderPlaced` to v3.

Two rounds of change land here:

* v1 -> v2: rename `customer_name` to `customer`, add `currency` (with a
  default), and register an upcaster.
* v2 -> v3: add an optional `placed_at`, and register a second upcaster.

`OrderCreated` is an older event that has been deprecated and superseded by
`OrderPlaced`.
"""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.upcaster import BaseUpcaster
from protean.fields import DateTime, Identifier, Integer, String
from protean.utils.mixins import handle

domain = Domain(name="Ordering")


@domain.aggregate
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    __version__ = 3
    order_id = Identifier(identifier=True)
    amount = Integer(required=True)
    customer = String(required=True, renamed_from=["customer_name"])
    currency = String(default="USD")
    placed_at = DateTime()


@domain.event(
    part_of=Order,
    deprecated={"since": "0.16", "removal": "0.19"},
    superseded_by="OrderPlaced",
)
class OrderCreated(BaseEvent):
    order_id = Identifier(identifier=True)


@domain.event_handler(part_of=Order)
class OrderNotifications(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class OrderPlacedV1toV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["customer"] = data.pop("customer_name")
        data.setdefault("currency", "USD")
        return data


@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class OrderPlacedV2toV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data.setdefault("placed_at", None)
        return data
