# --8<-- [start:full]
from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

domain = Domain(name="Ordering")


@domain.aggregate
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)


# --8<-- [start:after]
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    __version__ = 2
    order_id = Identifier(required=True)
    amount = Float(required=True)
    currency = String(required=True)


# --8<-- [end:after]


# --8<-- [start:upcaster]
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        # All orders before v2 were in USD
        data["currency"] = "USD"
        return data


# --8<-- [end:upcaster]
# --8<-- [end:full]
