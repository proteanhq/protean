import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import ValueObject


class Foo(BaseValueObject):
    bar: str | None = None
    qux: str | None = None


class Address(BaseValueObject):
    unit_no: str | None = None
    street_no: str
    street_name: str
    province: str | None = None
    country: str
    zipcode: str


def test_that_a_vo_can_be_declared_optional():
    class Foobar(BaseAggregate):
        baz: str
        foo = ValueObject(Foo)

    try:
        Foobar(baz="baz")
    except ValidationError:
        pytest.fail("Incorrect validation on Value Object marked optional")


def test_that_a_vo_can_be_declared_mandatory():
    class Foobar(BaseAggregate):
        baz: str
        foo = ValueObject(Foo, required=True)

    with pytest.raises(ValidationError):
        Foobar(baz="baz")


def test_that_a_vo_can_have_mandatory_fields_but_declared_optional():
    class User(BaseAggregate):
        name: str
        address = ValueObject(Address)

    try:
        User(name="John Doe")
    except ValidationError:
        pytest.fail("Incorrect validation on Value Object marked optional")


def test_that_a_vo_can_have_mandatory_fields_and_can_be_declared_mandatory():
    class User(BaseAggregate):
        name: str
        address = ValueObject(Address, required=True)

    with pytest.raises(ValidationError):
        User(name="John Doe")
