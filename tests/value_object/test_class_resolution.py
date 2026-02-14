"""These tests ensure that the Value Object class is resolved correctly when it is specified as a string."""

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import ValueObject
from protean.utils.reflection import declared_fields


class Account(BaseAggregate):
    balance = ValueObject("Balance", required=True)
    kind: str


class Balance(BaseValueObject):
    currency: str | None = None
    amount: float | None = None


def test_value_object_class_resolution(test_domain):
    test_domain.register(Account)
    test_domain.register(Balance)

    # This should perform the class resolution
    test_domain.init(traverse=False)

    assert declared_fields(Account)["balance"].value_object_cls == Balance
