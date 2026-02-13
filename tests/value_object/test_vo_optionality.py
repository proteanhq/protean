import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject


class Foo(BaseValueObject):
    bar = String()
    qux = String()


class Address(BaseValueObject):
    unit_no = String()
    street_no = String(required=True)
    street_name = String(required=True)
    province = String()
    country = String(required=True)
    zipcode = String(required=True)


def test_that_a_vo_can_be_declared_optional():
    class Foobar(BaseAggregate):
        baz = String(required=True)
        foo = ValueObject(Foo)

    try:
        Foobar(baz="baz")
    except ValidationError:
        pytest.fail("Incorrect validation on Value Object marked optional")


def test_that_a_vo_can_be_declared_mandatory():
    class Foobar(BaseAggregate):
        baz = String(required=True)
        foo = ValueObject(Foo, required=True)

    with pytest.raises(ValidationError):
        Foobar(baz="baz")


def test_that_a_vo_can_have_mandatory_fields_but_declared_optional():
    class User(BaseAggregate):
        name = String(required=True)
        address = ValueObject(Address)

    try:
        User(name="John Doe")
    except ValidationError:
        pytest.fail("Incorrect validation on Value Object marked optional")


def test_that_a_vo_can_have_mandatory_fields_and_can_be_declared_mandatory():
    class User(BaseAggregate):
        name = String(required=True)
        address = ValueObject(Address, required=True)

    with pytest.raises(ValidationError):
        User(name="John Doe")
