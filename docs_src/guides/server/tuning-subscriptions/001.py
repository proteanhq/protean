from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier

domain = Domain(
    name="Shop",
    config={"server": {"default_subscription_type": "stream"}},
)


# --8<-- [start:model]
@domain.aggregate
class Order:
    total: Float(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


# --8<-- [end:model]


# --8<-- [start:handler]
@domain.event_handler(part_of=Order, sequential_by="order_id")
class OrderHandler:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None: ...


# --8<-- [end:handler]


def place_order(total: float) -> Order:
    order = Order(total=total)
    order.raise_(OrderPlaced(order_id=order.id, total=total))
    current_domain.repository_for(Order).add(order)
    return order
