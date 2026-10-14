from protean import Domain, apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, List, String

domain = Domain(name="ReplayWithUpcasting")


@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 3
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    line_items = List(required=True)
    subtotal = Float(required=True)
    tax = Float(required=True)
    total = Float(required=True)
    currency = String(required=True)


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastOrderPlacedV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["line_items"] = data.pop("items", [])
        data["subtotal"] = data["total"]
        data["tax"] = 0.0
        return data


# --8<-- [start:aggregate]
@domain.aggregate(event_sourced=True)
class Order:
    customer_id = Identifier()
    items = List()
    total = Float()
    currency = String()

    @apply
    def on_order_placed(self, event: OrderPlaced):
        """Always receives current schema — upcasters handle old versions."""
        self.customer_id = event.customer_id
        self.items = event.line_items
        self.total = event.total
        self.currency = event.currency


# --8<-- [end:aggregate]
