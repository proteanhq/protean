"""Strict-typed sample domain: it must pass ``mypy --strict`` with no errors.

Written in the canonical typed-annotation style, it exercises the surface the
framework generates: field declarations, construction by keyword, handlers,
the query and dispatch path, repositories, views and caches.
"""

from typing import Any

from protean import Domain, current_domain, handle, read
from protean.core.aggregate import apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import (
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)

shop = Domain(name="Shop")


@shop.value_object
class Money:
    amount: float = Float(required=True)
    currency: str = String(max_length=3, default="USD")


@shop.entity(part_of="Order")
class LineItem:
    sku: str = String(required=True)
    quantity: int = Integer(required=True)
    price: Money = ValueObject(Money, required=True)


@shop.event(part_of="Order")
class OrderPlaced:
    order_id: str = Identifier(required=True)
    customer: str = String(required=True)
    total: float = Float(required=True)
    details: dict[str, Any] = Dict()


@shop.aggregate
class Order:
    customer: str = String(required=True, max_length=50)
    status: str = String(default="DRAFT")
    tags: list[str] = List(content_type=String)
    discount: Money | None = ValueObject(Money)
    items: list[LineItem] = HasMany(LineItem)

    def total(self) -> float:
        return sum(item.price.amount * item.quantity for item in self.items)

    def place(self) -> None:
        self.status = "PLACED"
        self.raise_(
            OrderPlaced(order_id=self.id, customer=self.customer, total=self.total())
        )


@shop.command(part_of=Order)
class PlaceOrder:
    customer: str = String(required=True)
    skus: list[str] = List(content_type=String)


@shop.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> str:
        order = Order(customer=command.customer)
        for sku in command.skus:
            order.add_items(LineItem(sku=sku, quantity=1, price=Money(amount=10.0)))
        order.place()
        current_domain.repository_for(Order).add(order)
        return order.id


@shop.event_handler(part_of=Order)
class OrderAudit:
    @handle("$any")
    def record(self, event: Any) -> None: ...


@shop.projection
class OrderSummary:
    order_id: str = Identifier(identifier=True)
    customer: str = String(required=True)
    total: float | None = Float()


@shop.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        summary = OrderSummary(
            order_id=event.order_id, customer=event.customer, total=event.total
        )
        current_domain.repository_for(OrderSummary).add(summary)


@shop.query(part_of=OrderSummary)
class GetOrderSummary:
    order_id: str = Identifier(required=True)


@shop.query_handler(part_of=OrderSummary)
class OrderSummaryQueries:
    @read(GetOrderSummary)
    def get(self, query: GetOrderSummary) -> OrderSummary:
        return current_domain.view_for(OrderSummary).get(query.order_id)


@shop.event(part_of="Wallet")
class WalletOpened:
    __version__ = 2

    wallet_id: str = Identifier(required=True)
    owner: str = String(required=True)


@shop.aggregate(event_sourced=True)
class Wallet:
    owner: str | None = String()
    balance: float = Float(default=0.0)

    @classmethod
    def open(cls, owner: str) -> "Wallet":
        wallet = cls._create_new()
        wallet.raise_(WalletOpened(wallet_id=wallet.id, owner=owner))
        return wallet

    @apply
    def opened(self, event: WalletOpened) -> None:
        self.owner = event.owner
        self.balance = 0.0


@shop.upcaster(event_type=WalletOpened, from_version=1, to_version=2)
class UpcastWalletOpened(BaseUpcaster):
    def upcast(self, data: dict[str, Any]) -> dict[str, Any]:
        return data


@shop.domain_service(part_of=[Order, Wallet])
class Checkout:
    def __init__(self, order: Order, wallet: Wallet) -> None:
        super().__init__(order, wallet)
        self.order = order
        self.wallet = wallet

    def __call__(self) -> bool:
        return self.wallet.balance >= self.order.total()


def place(customer: str) -> str:
    return str(shop.process(PlaceOrder(customer=customer, skus=["A1"])))


def summary_for(order_id: str) -> OrderSummary:
    view = shop.view_for(OrderSummary)
    rows = view.query.filter(customer="Ada").order_by("order_id").all()
    if rows.total > 0:
        return view.get(order_id)
    found: OrderSummary = shop.dispatch(GetOrderSummary(order_id=order_id))
    return found
