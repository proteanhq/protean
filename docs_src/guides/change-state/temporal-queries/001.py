# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean import Domain, UnitOfWork, apply
from protean.fields import Identifier, Integer, String

domain = Domain(name="Shop")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer: String(required=True)


@domain.event(part_of="Order")
class ItemAdded:
    order_id: Identifier(required=True)
    product: String(required=True)
    quantity: Integer(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    order_id: Identifier(identifier=True)
    customer: String(required=True)
    item_count: Integer(default=0)

    @classmethod
    def place(cls, order_id: str, customer: str) -> "Order":
        order = cls(order_id=order_id, customer=customer)
        order.raise_(OrderPlaced(order_id=order_id, customer=customer))
        return order

    def add_item(self, product: str, quantity: int) -> None:
        self.raise_(
            ItemAdded(order_id=self.order_id, product=product, quantity=quantity)
        )

    @apply
    def placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.customer = event.customer
        self.item_count = 0

    @apply
    def item_added(self, event: ItemAdded) -> None:
        self.item_count += event.quantity


domain.init(traverse=False)
# --8<-- [end:aggregate]

# --8<-- [start:history]
with domain.domain_context():
    repo = domain.repository_for(Order)

    # Versions 0 to 3: the order is placed and three items are added
    order = Order.place("order-123", customer="Alice")
    for product in ("pen", "ink", "paper"):
        order.add_item(product, quantity=1)
    repo.add(order)

    cutoff = datetime.now(UTC)

    # Versions 4 to 6: three more items, written after `cutoff`
    order = repo.get("order-123")
    for product in ("stapler", "tape", "glue"):
        order.add_item(product, quantity=2)
    repo.add(order)
# --8<-- [end:history]

# --8<-- [start:at_version]
with domain.domain_context():
    repo = domain.repository_for(Order)

    # State after the 6th event (version 5)
    order_v5 = repo.get("order-123", at_version=5)

    assert order_v5._version == 5
# --8<-- [end:at_version]

# --8<-- [start:is_temporal]
assert order_v5._is_temporal is True
# --8<-- [end:is_temporal]

# --8<-- [start:as_of]
with domain.domain_context():
    repo = domain.repository_for(Order)

    # The order as it stood at `cutoff`, before the last three items.
    # `cutoff` can be any datetime, for example
    # datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC) for noon on February 20.
    order_then = repo.get("order-123", as_of=cutoff)
# --8<-- [end:as_of]

# --8<-- [start:identity_map]
with domain.domain_context():
    repo = domain.repository_for(Order)

    with UnitOfWork():
        current = repo.get("order-123")
        current.add_item("pencil", quantity=1)  # Mutated in memory
        repo.add(current)  # Tracked in the identity map until commit
        assert repo.get("order-123") is current  # Served from the identity map

        historical = repo.get("order-123", at_version=0)  # Fresh from events
        assert historical._version == 0  # Not affected by in-memory mutation
# --8<-- [end:identity_map]
