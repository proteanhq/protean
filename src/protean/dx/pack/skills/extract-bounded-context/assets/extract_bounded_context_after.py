"""
Sales and fulfilment split into two `Domain` objects (after extraction).

This is extract_bounded_context_before.py with the two contexts pulled apart:

- The sales domain owns `Order` and raises `OrderPlaced` when an order is placed.
  It holds no reference into fulfilment.
- The fulfilment domain owns `Shipment`. It learns about a placed order from a
  subscriber that reads the sales event off a broker stream, translates it in an
  anti-corruption layer, and dispatches a domain command. `Shipment` holds the
  order by identity (`order_id`), not by a `Reference` back into sales.

Neither domain references the other's aggregates, so the cycle is gone: `check`
reports no `CIRCULAR_CLUSTER_DEPENDENCY` and no `CROSS_AGGREGATE_REFERENCE` on
either domain.

How the event crosses the seam. `OrderPlaced` is marked `published=True`, sales
turns the outbox on, and sales names an external broker, so a deployed sales
domain hands the event to that broker for fulfilment to read. This example runs
both domains in one process with no outbox relay running, so the demo does the
relay's job by hand.

The hand relay delivers exactly what a deployed relay delivers, so the subscriber
here is the subscriber you would deploy:

- it publishes on the aggregate's `stream_category` (`sales::order`), which is
  the stream `OutboxProcessor` reads off `metadata.domain.stream_category`;
- it publishes `Message.to_external_dict()`, the `{"data": ..., "metadata": ...}`
  envelope external consumers receive, so the subscriber unwraps `payload["data"]`.
"""

from protean import Domain, handle
from protean.fields import Identifier, String

# --- Sales context: owns Order, publishes OrderPlaced ---

sales = Domain(name="Sales")
sales.config["command_processing"] = "sync"
sales.config["event_processing"] = "sync"
# Turn the outbox on. `Domain.has_outbox` reads this setting, and it is false
# under the default "event_store" subscription. Naming an external broker below
# without this does nothing: the unit of work writes no outbox row, so nothing
# is ever dispatched outside the context.
sales.config["server"]["default_subscription_type"] = "stream"
# OrderPlaced is published outside the sales context, so it needs an external
# broker to go to. Configuring one clears the `PUBLISHED_NO_EXTERNAL_BROKER`
# warning `check` would otherwise report. A deployed sales domain dispatches
# published events to this broker; fulfilment reads them from it.
sales.config["brokers"]["events"] = {"provider": "inline"}
sales.config["outbox"]["external_brokers"] = ["events"]


# `published=True` marks OrderPlaced as part of the sales context's published
# language: it is meant to be consumed outside this domain, so `check` does not
# ask for an in-domain handler for it.
@sales.event(part_of="Order", published=True)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    address = String(required=True)


@sales.aggregate
class Order:
    customer_id = String(required=True, max_length=50)
    address = String(required=True, max_length=200)
    status = String(default="placed", max_length=20)

    def place(self) -> None:
        """Place the order and raise OrderPlaced for fulfilment to read."""
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                address=self.address,
            )
        )


@sales.command(part_of="Order")
class PlaceOrder:
    customer_id = String(required=True)
    address = String(required=True)


@sales.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id, address=command.address)
        order.place()
        sales.repository_for(Order).add(order)


# --- Fulfilment context: owns Shipment, consumes the sales event ---

fulfilment = Domain(name="Fulfilment")
fulfilment.config["command_processing"] = "sync"
fulfilment.config["message_processing"] = "sync"
# Broker names are local to each `Domain`, so configuring `events` on sales does
# not give fulfilment a broker by that name. Fulfilment declares its own entry,
# and the subscriber binds to it by name below. Without this the sales outbox
# would publish to sales' `events` broker while fulfilment listened on its own
# `default`, and nothing would arrive.
#
# `inline` is demo-only, and it is the one place this example departs from a
# deployment. Each `Domain` builds its own `InlineBroker` with its own messages
# and subscribers, so these two `events` entries are two separate objects, not
# one shared bus. `relay_last_order_event` below is what carries the message
# from sales' instance to fulfilment's. Deployed, you point both configs at the
# same broker endpoint (the same Redis, say) and the outbox relay does it.
fulfilment.config["brokers"]["events"] = {"provider": "inline"}


@fulfilment.aggregate
class Shipment:
    # The order is held by identity across the seam, not by a Reference into the
    # sales domain. That is what keeps the contexts free of the cycle.
    order_id = Identifier(required=True)
    address = String(required=True, max_length=200)
    status = String(default="pending", max_length=20)


@fulfilment.command(part_of="Shipment")
class CreateShipment:
    order_id = Identifier(required=True)
    address = String(required=True)


@fulfilment.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    @handle(CreateShipment)
    def create_shipment(self, command: CreateShipment) -> None:
        shipment = Shipment(order_id=command.order_id, address=command.address)
        fulfilment.repository_for(Shipment).add(shipment)


# The message type fulfilment agrees to accept, written out as the string sales
# puts on the wire. Fulfilment does not import `OrderPlaced` to get it: the
# extraction exists to end that dependency, and once the two contexts live in
# separate modules or processes the import is not available anyway. The contract
# fulfilment depends on is this name and the fields it unpacks below.
SALES_ORDER_PLACED = "Sales.OrderPlaced.v1"


# The stream is the sales aggregate's category, `sales::order`. That is what the
# outbox publishes on: `OutboxProcessor` routes each row by
# `metadata.domain.stream_category`, not by the event's own name. `broker` names
# fulfilment's own `events` entry, the one a deployed pair would point at the
# same endpoint as sales'.
@fulfilment.subscriber(stream="sales::order", broker="events")
class OrderPlacedSubscriber:
    """Anti-corruption layer for the sales `OrderPlaced` event.

    `OrderPlaced` belongs to the sales context's published language. Fulfilment
    reads the raw message off the broker stream and translates it into its own
    command here, so the sales event's shape stays out of the rest of the
    fulfilment context.
    """

    def __call__(self, payload: dict) -> None:
        # External delivery carries the full `{"data": ..., "metadata": ...}`
        # envelope, so the event's fields sit under "data". The category stream
        # carries every Order event, so ignore the ones fulfilment does not act
        # on.
        if payload["metadata"]["headers"]["type"] != SALES_ORDER_PLACED:
            return
        data = payload["data"]
        command = CreateShipment(
            order_id=data["order_id"],
            address=data["address"],
        )
        fulfilment.process(command)


def relay_last_order_event() -> None:
    """Stand in for the outbox relay a deployed system would run.

    A deployed sales domain runs `OutboxProcessor`, which publishes each row to
    the external broker on `metadata.domain.stream_category` as the envelope
    `Message.to_external_dict()` returns. Both domains run in one process here
    with no processor running, so this does the same two things by hand. It
    publishes what the real relay publishes, so the subscriber above is the one
    you would deploy.
    """
    with sales.domain_context():
        message = sales.event_store.store.read(Order.meta_.stream_category)[-1]

    with fulfilment.domain_context():
        # `events` on both sides, the broker sales dispatches to and fulfilment
        # subscribes on. Publishing to fulfilment's `default` here would deliver
        # the message in this one process while a deployed pair stayed silent.
        fulfilment.brokers["events"].publish(
            message.metadata.domain.stream_category,
            message.to_external_dict(),
        )


if __name__ == "__main__":
    sales.init(traverse=False)
    fulfilment.init(traverse=False)

    with sales.domain_context():
        sales.process(PlaceOrder(customer_id="CUST-1", address="1 Market St"))

    relay_last_order_event()

    with fulfilment.domain_context():
        shipments = fulfilment.repository_for(Shipment).query.all()
        print(f"fulfilment opened {shipments.total} shipment(s) from the sales event")
