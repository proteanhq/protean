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

How the event crosses the seam. `OrderPlaced` is marked `published=True`, and
sales configures `outbox.external_brokers`, so a deployed sales domain hands the
event to that broker for fulfilment to read. This example runs both domains in
one process with no outbox relay running, so the demo does the relay's job by
hand: it reads the `OrderPlaced` fact the sales context recorded and publishes it
to the broker stream the fulfilment subscriber reads.
"""

from protean import Domain, handle
from protean.fields import Identifier, String

# --- Sales context: owns Order, publishes OrderPlaced ---

sales = Domain(name="Sales")
sales.config["command_processing"] = "sync"
sales.config["event_processing"] = "sync"
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


@fulfilment.subscriber(stream="sales_order_placed")
class OrderPlacedSubscriber:
    """Anti-corruption layer for the sales `OrderPlaced` event.

    `OrderPlaced` belongs to the sales context's published language. Fulfilment
    reads the raw payload off the broker stream and translates it into its own
    command here, so the sales event's shape stays out of the rest of the
    fulfilment context.
    """

    def __call__(self, payload: dict) -> None:
        command = CreateShipment(
            order_id=payload["order_id"],
            address=payload["address"],
        )
        fulfilment.process(command)


if __name__ == "__main__":
    sales.init(traverse=False)
    fulfilment.init(traverse=False)

    with sales.domain_context():
        sales.process(PlaceOrder(customer_id="CUST-1", address="1 Market St"))
        # The OrderPlaced fact the sales context recorded while handling the
        # command. A deployed outbox relay reads it here and hands it to the
        # external broker.
        fact = sales.event_store.store.read(Order.meta_.stream_category)[-1]

    # Stand in for the relay: hand the recorded event to the broker stream the
    # fulfilment subscriber reads. A deployed system runs the outbox relay for
    # this; one process has none, so the demo does it by hand.
    with fulfilment.domain_context():
        fulfilment.brokers["default"].publish(
            "sales_order_placed",
            {"order_id": fact.data["order_id"], "address": fact.data["address"]},
        )
        shipments = fulfilment.repository_for(Shipment).query.all()
        print(f"fulfilment opened {shipments.total} shipment(s) from the sales event")
