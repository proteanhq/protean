"""Fixture: framework entry points return the element class they were given."""

from protean.core.aggregate import apply
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Identifier, String

domain = Domain(name="Strict")


@domain.event(part_of="Order")
class OrderCreated:
    order_id: str = Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    order_id: str = Identifier(identifier=True)
    status: str | None = String()

    @classmethod
    def create(cls) -> "Order":
        order = cls._create_new()
        order.raise_(OrderCreated(order_id=str(order.id)))
        return order

    @apply
    def created(self, event: OrderCreated) -> None:
        self.status = "CREATED"


@domain.projection
class ProductCard:
    product_id: str = Identifier(identifier=True)
    name: str | None = String()


@domain.aggregate
class Account:
    account_id: str = Identifier(identifier=True)


@domain.domain_service(part_of=[Account, Account])
class TransferPoints:
    def __init__(self, source: Account, target: Account) -> None:
        super().__init__(source, target)


reveal_type(Order._create_new())  # R: Order
reveal_type(Order.from_events([]))  # R: Order

view = domain.view_for(ProductCard)
reveal_type(view)  # R: ReadView[ProductCard]
reveal_type(view.get("p1"))  # R: ProductCard
reveal_type(view.get("p1").name)  # R: str | None
reveal_type(view.find_by(name="x"))  # R: ProductCard

TransferPoints(Account(account_id="a"), Account(account_id="b"))

# An event is a BaseEvent, so it can go where the framework asks for one.
event: BaseEvent = OrderCreated(order_id="o1")
