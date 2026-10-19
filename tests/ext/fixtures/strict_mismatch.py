"""Fixture: the annotation and the field call check each other."""

from protean.domain import Domain
from protean.fields import Integer, String, ValueObject

domain = Domain(name="Strict")


@domain.value_object
class Money:
    amount: int = Integer(required=True)


@domain.aggregate
class Order:
    count: int = String(required=True)  # E: assignment
    name: str = String()  # E: assignment
    total: Money = ValueObject(Money)  # E: assignment
    ok: str | None = String()
