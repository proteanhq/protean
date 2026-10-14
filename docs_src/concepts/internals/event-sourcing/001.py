from protean import Domain, apply
from protean.fields import Identifier, String

domain = Domain(name="Ordering")


# --8<-- [start:place]
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    customer_name: String(required=True)
    status: String(required=True)

    @classmethod
    def place(cls, customer_name):
        order = cls._create_new()
        order.raise_(
            OrderPlaced(
                order_id=str(order.id),
                customer_name=customer_name,
            )
        )
        return order

    def confirm(self):
        self.raise_(OrderConfirmed(order_id=str(self.id)))

    @apply
    def placed(self, event: OrderPlaced):
        self.id = event.order_id
        self.customer_name = event.customer_name
        self.status = "PLACED"

    @apply
    def confirmed(self, event: OrderConfirmed):
        self.status = "CONFIRMED"


# --8<-- [end:place]
