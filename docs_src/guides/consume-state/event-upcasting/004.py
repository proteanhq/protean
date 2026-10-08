# --8<-- [start:chain]
from protean import Domain
from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String
from protean.utils.mixins import handle

domain = Domain(name="Ordering")


# v1: original schema
# v2: added currency
# v3: renamed amount → total_amount


@domain.event(part_of="Order")
class OrderPlaced(BaseEvent):
    __version__ = 3
    order_id = Identifier(required=True)
    total_amount = Float(required=True)
    currency = String(required=True)


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastOrderPlacedV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data


# --8<-- [end:chain]


# --8<-- [start:aggregate]
@domain.aggregate(event_sourced=True)
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    total_amount = Float()
    currency = String()

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        # Always receives current v3 schema
        self.order_id = event.order_id
        self.total_amount = event.total_amount
        self.currency = event.currency


# --8<-- [end:aggregate]


# --8<-- [start:handler]
revenue_by_currency: dict[str, float] = {}


def record_revenue(amount: float, currency: str) -> None:
    revenue_by_currency[currency] = revenue_by_currency.get(currency, 0.0) + amount


@domain.event_handler(part_of=Order)
class AnalyticsHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Always receives current schema, even for historical replays
        record_revenue(event.total_amount, event.currency)


# --8<-- [end:handler]
