# --8<-- [start:full]
from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Ordering")


# 1. Define the aggregate and event
@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    status: String(max_length=20, default="DRAFT")

    def place(self):
        self.status = "PLACED"
        self.raise_(
            OrderPlaced(
                order_id=str(self.id),
                customer_name=self.customer_name,
            )
        )


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_name = String(max_length=100)


# 2. Define a handler that reacts to the event
@domain.event_handler(part_of=Order)
class OrderPlacedNotification:
    @handle(OrderPlaced)
    def send_confirmation(self, event: OrderPlaced):
        print(f"Order {event.order_id} placed for {event.customer_name}")


# --8<-- [end:full]
