"""
Sales and fulfilment split into two `Domain` objects that talk by events across
the seam (after extraction).

This is extract_bounded_context_before.py with the contexts pulled apart:

- The sales domain owns `Order` and publishes `OrderPlaced` when an order is
  placed. It holds no reference into fulfilment.
- The fulfilment domain owns `Shipment`. It learns about a placed order through
  a subscriber that consumes the sales event off a broker stream, translates it
  in an anti-corruption layer, and dispatches a domain command. `Shipment` holds
  the order by identity (`order_id`), not by a `Reference` back into sales.

Neither domain references the other's aggregates, so the cycle is gone:
`check` reports no `CIRCULAR_CLUSTER_DEPENDENCY` and no `CROSS_AGGREGATE_REFERENCE`
on either domain.

The seam is a message broker. Here both domains run in one process, so the demo
block bridges them by hand: it takes the payload the sales event carries and
publishes it to the fulfilment broker stream the subscriber listens on. A
deployed system puts a real broker or relay in that gap.
"""

from protean import Domain, handle
from protean.fields import Identifier, String

# --- Sales context: owns Order, publishes OrderPlaced ---

sales = Domain(name="Sales")
sales.config["command_processing"] = "sync"
sales.config["event_processing"] = "sync"
# OrderPlaced leaves the sales context, so it dispatches to an external broker
# the fulfilment context can read. Naming that broker here is what keeps the
# published event honestly wired.
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
        """Place the order and announce it across the seam."""
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

    The sales context owns the meaning of `OrderPlaced`. Fulfilment consumes the
    raw payload off the broker stream and translates it into its own command, so
    the sales event's shape never leaks past this boundary.
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
        order = Order(customer_id="CUST-1", address="1 Market St")
        order.place()
        # The event the sales context published, captured before it is persisted.
        placed = order._events[-1]
        sales.repository_for(Order).add(order)

    # Bridge the seam: in production a broker or relay carries this. Here we hand
    # the payload to the fulfilment stream the subscriber listens on.
    with fulfilment.domain_context():
        fulfilment.brokers["default"].publish(
            "sales_order_placed",
            {"order_id": placed.order_id, "address": placed.address},
        )
        shipments = fulfilment.repository_for(Shipment)._dao.query.all().items
        print(f"fulfilment opened {len(shipments)} shipment(s) from the sales event")
