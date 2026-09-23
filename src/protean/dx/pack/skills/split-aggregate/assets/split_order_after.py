"""
Order split into Order and Shipment, after the refactor.

The fulfilment concern moved out of Order into its own Shipment aggregate. Each
cluster now holds fewer child entities than the default `aggregate_size_limit`
allows, so `check` no longer reports AGGREGATE_TOO_LARGE.

Shipment links back to Order by identity: it holds the order's id in a plain
`Identifier` field. Reaching across to the `Order` root with a `Reference` field
is what `check` reports as CROSS_AGGREGATE_REFERENCE; the identity link is the
shape that avoids it. Here that field is also Shipment's own identity, so an
order has one shipment and a redelivered OrderPlaced cannot open a second one.

Order and Shipment stay decoupled through a domain event. Order raises
OrderPlaced when it is placed. An event handler in Order's own cluster reacts to
that event and issues a StartShipment command, and Shipment's command handler
creates the shipment. Order never holds a handle to Shipment; it only emits the
fact that it was placed.

Processing is synchronous, so one PlaceOrder command runs the whole hop
in-process, with no broker and no server. A deployed domain leaves both
asynchronous and lets the server drive the step.

Usage:
    from split_order_after import PlaceOrder, domain

    domain.init(traverse=False)
    with domain.domain_context():
        # Places the order, which starts its shipment by identity.
        domain.process(
            PlaceOrder(order_id="ORD-001", customer_id="CUST-1", total=100.0)
        )
"""

from protean import Domain, current_domain, handle, invariant
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import DateTime, Float, HasMany, Identifier, Integer, String

domain = Domain(__file__, "ecommerce")

# Run the hop in-process: OrderPlaced reaches the event handler as soon as the
# order is saved, and StartShipment reaches its handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Commands ---


@domain.command(part_of="Order")
class PlaceOrder:
    """Place an order. The caller chooses the order id."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.command(part_of="Shipment")
class StartShipment:
    """Start the shipment for a placed order, by the order's identity."""

    order_id: Identifier(required=True)


# --- Events ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when an order is placed."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


# --- Order aggregate (order concern only) ---


@domain.aggregate
class Order:
    """The order, with the fulfilment concern removed."""

    customer_id: Identifier(required=True)
    total: Float(default=0.0)
    status: String(default="draft")

    items = HasMany("OrderItem")
    discounts = HasMany("Discount")
    gift_wraps = HasMany("GiftWrap")

    @classmethod
    def place(cls, order_id: str, customer_id: str, total: float) -> "Order":
        """Place an order and report it with OrderPlaced."""
        order = cls(id=order_id, customer_id=customer_id, total=total, status="placed")
        order.raise_(
            OrderPlaced(order_id=order.id, customer_id=customer_id, total=total)
        )
        return order

    @invariant.post
    def total_must_not_be_negative(self) -> None:
        """An order's total cannot be negative."""
        if self.total < 0:
            raise ValidationError({"total": ["Order total cannot be negative"]})


@domain.entity(part_of="Order")
class OrderItem:
    """A line on the order."""

    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)


@domain.entity(part_of="Order")
class Discount:
    """A discount applied to the order."""

    code: String(required=True, max_length=50)
    amount: Float(required=True, min_value=0.0)


@domain.entity(part_of="Order")
class GiftWrap:
    """A gift-wrap request on the order."""

    style: String(required=True, max_length=50)


# --- Shipment aggregate (the fulfilment concern, extracted) ---


@domain.aggregate
class Shipment:
    """The shipment for an order.

    `order_id` is the identity link back to Order: the order's id held in a
    plain field. A `Reference` to the Order root here is what trips
    CROSS_AGGREGATE_REFERENCE.

    It is also the shipment's own identity. This example gives an order one
    shipment, so the order's id identifies the shipment too, and a second
    shipment for the same order cannot be stored. That matters because events
    are delivered at least once: without a deterministic id, a redelivered
    OrderPlaced would insert a second shipment under a fresh auto-generated id.
    A domain that ships one order in several parcels would give Shipment its own
    id instead. The handler guard below reads a shipment by `order_id` because
    `order_id` is the identity here, so that domain would have to guard on a
    deterministic shipment id carried on the command.
    """

    order_id: Identifier(identifier=True)
    status: String(default="pending")

    packages = HasMany("Package")
    tracking_events = HasMany("TrackingEvent")
    delivery_attempts = HasMany("DeliveryAttempt")

    @classmethod
    def start(cls, order_id: str) -> "Shipment":
        """Start a shipment for a placed order."""
        return cls(order_id=order_id, status="pending")

    @invariant.post
    def cannot_be_delivered_before_it_is_packed(self) -> None:
        """Nothing can be out for delivery before it has been packed.

        This rule spans two of the extracted entities, which is the argument for
        making fulfilment its own aggregate: they have to stay correct together,
        in one transaction.
        """
        if self.delivery_attempts and not self.packages:
            raise ValidationError(
                {
                    "delivery_attempts": [
                        "A shipment cannot be delivered before it is packed"
                    ]
                }
            )


@domain.entity(part_of="Shipment")
class Package:
    """A physical package prepared for the order."""

    weight_kg: Float(required=True, min_value=0.0)


@domain.entity(part_of="Shipment")
class TrackingEvent:
    """A carrier tracking update for the shipment."""

    status: String(required=True, max_length=50)
    note: String(max_length=200)


@domain.entity(part_of="Shipment")
class DeliveryAttempt:
    """One attempt to deliver the shipment."""

    attempted_at: DateTime()
    outcome: String(required=True, max_length=50)


# --- Command handlers (the write path for each aggregate) ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """The write path for Order."""

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order.place(command.order_id, command.customer_id, command.total)
        current_domain.repository_for(Order).add(order)


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    """The write path for Shipment."""

    @handle(StartShipment)
    def start_shipment(self, command: StartShipment) -> None:
        repository = current_domain.repository_for(Shipment)
        try:
            repository.get(command.order_id)
        except ObjectNotFoundError:
            repository.add(Shipment.start(command.order_id))
        else:
            # The shipment is already open. A redelivered OrderPlaced reissues
            # StartShipment, and starting over would throw away whatever
            # progress the shipment has made since.
            return


# --- The cross-aggregate link: a domain event, not a reference ---


@domain.event_handler(part_of=Order)
class ShipmentInitiation:
    """React to Order's own OrderPlaced event and start its shipment.

    The handler sits in Order's cluster, because it reacts to Order's own event
    (a handler that reacts to another cluster's event is what `check` reports as
    EVENT_HANDLER_FOREIGN_EVENT). It hands off to Shipment by issuing a command,
    so Order and Shipment stay linked by identity and by this event, never by a
    direct object reference.
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        current_domain.process(StartShipment(order_id=event.order_id))
