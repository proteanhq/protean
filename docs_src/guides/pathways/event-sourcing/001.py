# --8<-- [start:aggregate]
from protean import Domain, apply
from protean.fields import Float, Identifier, String

domain = Domain(name="Ordering")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    order_id: Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    status: String(default="draft")
    total: Float(default=0.0)

    def place(self):
        self.raise_(OrderPlaced(order_id=self.id, total=self.total))

    @apply
    def placed(self, event: OrderPlaced):
        self.id = event.order_id
        self.status = "placed"
        self.total = event.total

    @apply
    def cancelled(self, event: OrderCancelled):
        self.status = "cancelled"


# --8<-- [end:aggregate]
