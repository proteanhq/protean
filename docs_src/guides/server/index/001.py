from protean import Domain, handle
from protean.fields import Identifier

domain = Domain(name="Orders")

placed_orders = []


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.event_handler(part_of=Order)
class OrderNotifications:
    @handle(OrderPlaced)
    def record(self, event: OrderPlaced) -> None:
        placed_orders.append(event.order_id)
        print(f"Handled {event.order_id}", flush=True)


def place_order(order_id: str) -> None:
    order = Order(order_id=order_id)
    order.raise_(OrderPlaced(order_id=order_id))
    domain.repository_for(Order).add(order)


# --8<-- [start:engine]
from protean.server import Engine


def serve():
    # Create and run the engine
    engine = Engine(domain)
    engine.run()  # Blocking call


# --8<-- [end:engine]


# --8<-- [start:options]
def serve_with_debug_logging():
    engine = Engine(
        domain,
        test_mode=False,
        debug=True,
    )
    engine.run()


# --8<-- [end:options]
