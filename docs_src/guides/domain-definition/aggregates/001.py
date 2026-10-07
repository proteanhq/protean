from protean import Domain, apply
from protean.fields import String

domain = Domain(name="Ordering")


# --8<-- [start:aggregate]
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True)
    customer_name: String(max_length=150, required=True)


@domain.aggregate(event_sourced=True)
class Order:
    customer_name: String(max_length=150, required=True)
    status: String(max_length=20, default="PENDING")

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

    @apply
    def when_placed(self, event: OrderPlaced):
        self.customer_name = event.customer_name
        self.status = "PENDING"


# --8<-- [end:aggregate]
