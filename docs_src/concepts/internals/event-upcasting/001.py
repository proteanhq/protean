# --8<-- [start:events]
from protean import Domain, apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

domain = Domain(name="Ordering")


@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 3
    order_id: Identifier(required=True)
    total_amount: Float(required=True)
    currency: String(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    order_id: Identifier(identifier=True)
    total_amount: Float()
    currency: String()

    @apply
    def placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.total_amount = event.total_amount
        self.currency = event.currency


# --8<-- [end:events]


# --8<-- [start:registration]
# Decorator syntax
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class AddCurrency(BaseUpcaster):
    def upcast(self, data):
        data["currency"] = "USD"
        return data


# Direct registration (e.g. in test fixtures)
class RenameAmount(BaseUpcaster):
    def upcast(self, data):
        data["total_amount"] = data.pop("amount")
        return data


domain.upcaster(RenameAmount, event_type=OrderPlaced, from_version=2, to_version=3)
# --8<-- [end:registration]
