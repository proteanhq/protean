from protean import Domain, apply
from protean.fields import Identifier, String

domain = Domain()


# --8<-- [start:es_order]
@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    status: String(max_length=20, default="PENDING")

    def confirm(self):
        # Don't set self.status here. Raise an event instead.
        self.raise_(OrderConfirmed(order_id=self.id))

    @apply
    def when_confirmed(self, event: OrderConfirmed):
        # State mutation happens here, triggered by raise_()
        self.status = "CONFIRMED"


# --8<-- [end:es_order]
