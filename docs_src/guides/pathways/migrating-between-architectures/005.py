from protean import Domain, apply, current_domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Shop", config={"command_processing": "sync"})


# --8<-- [start:event]
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float(required=True)


# --8<-- [end:event]


# --8<-- [start:aggregate]
@domain.aggregate(event_sourced=True)
class Order:
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()

    @classmethod
    def place(cls, order_id, customer_id, total):
        order = cls._create_new(id=order_id)
        order.raise_(
            OrderPlaced(
                order_id=order.id,
                customer_id=customer_id,
                total=total,
            )
        )
        return order

    @apply
    def on_placed(self, event: OrderPlaced):
        self.id = event.order_id
        self.customer_id = event.customer_id
        self.total = event.total
        self.status = "placed"


# --8<-- [end:aggregate]


# --8<-- [start:command]
@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float(required=True)


# --8<-- [end:command]


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order.place(
            order_id=command.order_id,
            customer_id=command.customer_id,
            total=command.total,
        )
        current_domain.repository_for(Order).add(order)


# --8<-- [end:handler]
