"""Fixture: the annotation-only field form under mypy --strict.

``name: String(...)`` puts a call in the annotation, which mypy rejects at
parse time and keeps no Python type for. The plugin drops the annotation and
accepts each field as a keyword, so construction by keyword is clean. The
fields resolve to ``Any``.
"""

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

domain = Domain(name="Strict")


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3)


@domain.entity(part_of="Order")
class LineItem:
    sku: String(required=True)
    quantity: Integer(default=1)


@domain.aggregate
class Order:
    customer: String(required=True, max_length=50)
    total: ValueObject(Money)
    lines: HasMany(LineItem)

    def describe(self) -> str:
        return f"{self.customer}: {len(self.lines)} lines"

    def rename(self, customer: str) -> None:
        self.customer = customer


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    customer: String()


@domain.query(part_of=OrderSummary)
class GetOrderSummary:
    order_id: Identifier(required=True)


# A class that inherits a Protean base explicitly gets the same salvage.
class Book(BaseAggregate):
    title: String(required=True)


order = Order(
    customer="Ada",
    total=Money(amount=1.5, currency="USD"),
    lines=[LineItem(sku="A1", quantity=2)],
)
order.add_lines(LineItem(sku="B2"))
PlaceOrder(order_id="o1")
OrderPlaced(order_id="o1")
OrderSummary(order_id="o1", customer="Ada")
GetOrderSummary(order_id="o1")
Book(title="Dune")
Book()

reveal_type(order.customer)  # R: Any


# A call without keyword arguments is a field only when it names a Protean
# field factory.
def make_label() -> str:
    return "label"


@domain.aggregate
class Misdeclared:
    label: make_label()  # E: valid-type


# An unknown keyword is still an error.
Order(customr="Ada")  # E: call-arg
