"""
Fact events generated from aggregate state with ``fact_events=True``.

This example demonstrates:
- Opting an aggregate into fact events with ``@domain.aggregate(fact_events=True)``
- The generated ``<Aggregate>FactEvent`` class (here ``OrderFactEvent``)
- Fact events being written when the repository persists the aggregate
- Reading a fact event back from the ``<stream_category>-fact-<id>`` stream
- Delta events, raised by hand, next to the generated fact events

You do not declare a fact event class. Protean builds one from the
aggregate's fields during ``domain.init()``. Each time the repository saves a
new or changed aggregate, it writes a fact event with the full aggregate
state. Saving an unchanged aggregate writes none.

Usage:
    domain.init(traverse=False)
    with domain.domain_context():
        order = Order(customer_id="CUST-123", total=Money(amount=99.99))
        domain.repository_for(Order).add(order)

        stream = f"{Order.meta_.stream_category}-fact-{order.id}"
        fact = domain.event_store.store.read(stream)[-1].to_domain_object()
        # fact is an OrderFactEvent carrying every Order field
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Float, HasMany, Integer, String, ValueObject

# Domain setup
domain = Domain(name="Shop")


@domain.value_object
class Money:
    """Value object for monetary amounts."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")


@domain.value_object
class Address:
    """Value object for addresses."""

    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)


# Delta events: raised by hand from business methods
@domain.event(part_of="Order")
class OrderPlaced:
    """Delta event: records only the placement."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    """Delta event: records only the shipment."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(required=True)


# Aggregate with fact events turned on
@domain.aggregate(fact_events=True)
class Order:
    """Order aggregate.

    Saving a new or changed order writes an ``OrderFactEvent`` with the
    complete order state. Saving an unchanged order writes none.
    """

    customer_id: String(required=True)
    status: String(default="draft")
    items = HasMany("OrderItem")
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)
    placed_at: DateTime()
    shipped_at: DateTime()
    tracking_number: String(max_length=50)

    def place(self) -> None:
        self.status = "placed"
        self.placed_at = datetime.now(UTC)
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                placed_at=self.placed_at,
            )
        )

    def ship(self, tracking_number: str) -> None:
        self.status = "shipped"
        self.shipped_at = datetime.now(UTC)
        self.tracking_number = tracking_number
        self.raise_(
            OrderShipped(
                order_id=self.id,
                shipped_at=self.shipped_at,
                tracking_number=tracking_number,
            )
        )


@domain.entity(part_of=Order)
class OrderItem:
    """Line item inside an order."""

    product_id: String(required=True)
    name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        order = Order(
            customer_id="CUST-67890",
            items=[
                OrderItem(
                    product_id="PROD-001",
                    name="Wireless Mouse",
                    quantity=2,
                    unit_price=29.99,
                ),
                OrderItem(
                    product_id="PROD-002",
                    name="USB Keyboard",
                    quantity=1,
                    unit_price=49.99,
                ),
            ],
            total=Money(amount=109.97, currency="USD"),
            shipping_address=Address(
                street="456 Market St",
                city="San Francisco",
                state="CA",
                postal_code="94102",
                country="USA",
            ),
        )
        order.place()

        repo = domain.repository_for(Order)
        repo.add(order)  # writes OrderPlaced and the first OrderFactEvent

        order = repo.get(order.id)
        order.ship("TRK-999888")
        repo.add(order)  # writes OrderShipped and a second OrderFactEvent

        stream = f"{Order.meta_.stream_category}-fact-{order.id}"
        messages = domain.event_store.store.read(stream)
        print(f"Fact events in {stream}: {len(messages)}")

        latest = messages[-1].to_domain_object()
        print(f"  Event: {latest.__class__.__name__}")
        print(f"  Status: {latest.status}")
        print(f"  Items: {len(latest.items)} items")
        print(f"  Total: {latest.total.amount} {latest.total.currency}")
        print(f"  Shipping city: {latest.shipping_address.city}")
        print(f"  Tracking number: {latest.tracking_number}")
