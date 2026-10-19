"""Fixture: the typed-annotation field form under mypy --strict.

Every decorated element kind that is constructed by keyword is declared with
``name: <type> = Field(...)``. Construction by keyword type-checks and each
field keeps its concrete type. Lines marked ``# R:`` carry the expected
revealed type, and lines marked ``# E:`` the expected error code.
"""

from typing import Any

from protean.domain import Domain
from protean.fields import (
    Float,
    HasMany,
    HasOne,
    Identifier,
    Integer,
    List,
    Reference,
    String,
    ValueObject,
)

domain = Domain(name="Strict")


@domain.value_object
class Money:
    amount: float = Float(required=True)
    currency: str | None = String(max_length=3)


@domain.entity(part_of="Order")
class LineItem:
    sku: str = String(required=True)
    quantity: int = Integer(default=1)
    order: "Order | None" = Reference("Order")


@domain.entity(part_of="Order")
class Shipment:
    carrier: str | None = String()


@domain.aggregate
class Order:
    customer: str = String(required=True, max_length=50)
    note: str | None = String()
    tags: list[str] = List(content_type=String)
    total: Money = ValueObject(Money, required=True)
    discount: Money | None = ValueObject(Money)
    lines: list[LineItem] = HasMany(LineItem)
    shipment: Shipment | None = HasOne(Shipment)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: str = Identifier(required=True)
    customer: str = String(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: str = Identifier(required=True)
    total: float | None = Float()


@domain.projection
class OrderSummary:
    order_id: str = Identifier(identifier=True)
    customer: str | None = String()


@domain.query(part_of=OrderSummary)
class GetOrderSummary:
    order_id: str = Identifier(required=True)


money = Money(amount=1.5, currency="USD")
line = LineItem(sku="A1", quantity=2)
order = Order(
    customer="Ada",
    total=money,
    discount=None,
    lines=[line],
    shipment=Shipment(carrier="UPS"),
)
command = PlaceOrder(order_id="o1", customer="Ada")
event = OrderPlaced(order_id="o1", total=1.5)
summary = OrderSummary(order_id="o1", customer="Ada")
query = GetOrderSummary(order_id="o1")

reveal_type(money.amount)  # R: float
reveal_type(money.currency)  # R: str | None
reveal_type(line.sku)  # R: str
reveal_type(line.quantity)  # R: int
reveal_type(order.customer)  # R: str
reveal_type(order.note)  # R: str | None
reveal_type(order.tags)  # R: list[str]
reveal_type(order.total)  # R: Money
reveal_type(order.total.amount)  # R: float
reveal_type(order.discount)  # R: Money | None
reveal_type(order.lines)  # R: list[LineItem]
reveal_type(order.shipment)  # R: Shipment | None
reveal_type(command.customer)  # R: str
reveal_type(event.total)  # R: float | None
reveal_type(summary.customer)  # R: str | None
reveal_type(query.order_id)  # R: str

# The assignment form follows the same rules for ValueObject.
required_vo = ValueObject(Money, required=True)
optional_vo = ValueObject(Money)
reveal_type(required_vo)  # R: Money
reveal_type(optional_vo)  # R: Money | None

# HasOne cannot be required at runtime, so it stays optional.
has_one = HasOne(Shipment, required=True)
reveal_type(has_one)  # R: Shipment | None

# Reference follows the scalar rule.
required_ref = Reference(Order, required=True)
optional_ref = Reference(Order)
reveal_type(required_ref)  # R: Order
reveal_type(optional_ref)  # R: Order | None

# ``default=None`` leaves the value None, so the field stays optional.
none_default_vo = ValueObject(Money, default=None)
none_default_str = String(default=None)
reveal_type(none_default_vo)  # R: Money | None
reveal_type(none_default_str)  # R: str | None

# A value object or reference left out reads as None even with a default.
defaulted_vo = ValueObject(Money, default=Money(amount=0))
reveal_type(defaulted_vo)  # R: Money | None


# An aggregate may declare its own identity type.
@domain.aggregate
class Counter:
    id: int = Integer(identifier=True)


reveal_type(Counter(id=1).id)  # R: int


@domain.aggregate
class Wallet:
    balance: Money | None = ValueObject(Money, default=Money(amount=0))


reveal_type(Wallet().balance)  # R: Money | None


# A target mypy cannot resolve leaves the field object's own type.
def embed(target: Any) -> None:
    reveal_type(ValueObject(target))  # R: ValueObject


# An unknown keyword is still an error on every kind.
Order(customr="Ada")  # E: call-arg
GetOrderSummary(order="o1")  # E: call-arg
