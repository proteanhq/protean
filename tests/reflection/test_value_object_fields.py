import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import ValueObject
from protean.utils.reflection import value_object_fields


class Address(BaseValueObject):
    street: str | None = None
    city: str | None = None
    postal_code: str | None = None


class Balance(BaseValueObject):
    amount: float
    currency: str = "USD"


class User(BaseAggregate):
    name: str
    age: int | None = None
    address = ValueObject(Address)


class Account(BaseAggregate):
    email: str
    balance = ValueObject(Balance)
    primary_address = ValueObject(Address)


class PersonWithoutValueObjects(BaseAggregate):
    name: str
    age: int | None = None


def test_value_object_fields():
    """Test that value_object_fields returns only ValueObject fields"""
    vo_fields = value_object_fields(User)

    assert len(vo_fields) == 1
    assert "address" in vo_fields
    assert isinstance(vo_fields["address"], ValueObject)


def test_value_object_fields_multiple_value_objects():
    """Test element with multiple ValueObject fields"""
    vo_fields = value_object_fields(Account)

    assert len(vo_fields) == 2
    assert "balance" in vo_fields
    assert "primary_address" in vo_fields
    assert all(isinstance(field, ValueObject) for field in vo_fields.values())


def test_value_object_fields_on_element_without_value_objects():
    """Test element with no ValueObject fields returns empty dict"""
    vo_fields = value_object_fields(PersonWithoutValueObjects)

    assert len(vo_fields) == 0
    assert vo_fields == {}


def test_value_object_fields_on_instance():
    """Test value_object_fields works with instances"""
    user = User(name="John Doe", age=30)
    vo_fields = value_object_fields(user)

    assert len(vo_fields) == 1
    assert "address" in vo_fields
    assert isinstance(vo_fields["address"], ValueObject)


def test_value_object_fields_excludes_non_value_object_fields():
    """Test that value_object_fields excludes regular fields and other types"""
    vo_fields = value_object_fields(User)

    # Should only include the ValueObject field, not String/Integer fields
    assert len(vo_fields) == 1
    assert "address" in vo_fields
    assert "name" not in vo_fields
    assert "age" not in vo_fields
    assert isinstance(vo_fields["address"], ValueObject)


def test_value_object_fields_on_non_element():
    """Test value_object_fields raises error on non-element class"""

    class Dummy:
        pass

    with pytest.raises(IncorrectUsageError) as exception:
        value_object_fields(Dummy)

    assert exception.value.args[0] == (
        "<class 'test_value_object_fields.test_value_object_fields_on_non_element.<locals>.Dummy'> "
        "does not have fields"
    )


def test_value_object_fields_with_string_reference():
    """Test ValueObject field defined with string class name"""

    class ProductWithStringRef(BaseAggregate):
        name: str | None = None
        shipping_address = ValueObject("Address")

    vo_fields = value_object_fields(ProductWithStringRef)

    assert len(vo_fields) == 1
    assert "shipping_address" in vo_fields
    assert isinstance(vo_fields["shipping_address"], ValueObject)


def test_value_object_fields_on_entity():
    """Test value_object_fields works on entities"""

    class OrderItem(BaseEntity):
        name: str | None = None
        price = ValueObject(Balance)

    vo_fields = value_object_fields(OrderItem)

    assert len(vo_fields) == 1
    assert "price" in vo_fields
    assert isinstance(vo_fields["price"], ValueObject)


def test_value_object_fields_mixed_with_other_fields():
    """Test element with mix of ValueObject and other field types"""

    class ComplexEntity(BaseAggregate):
        name: str | None = None
        age: int | None = None
        address = ValueObject(Address)
        balance = ValueObject(Balance)

    vo_fields = value_object_fields(ComplexEntity)

    # Should only return ValueObject fields
    assert len(vo_fields) == 2
    assert "address" in vo_fields
    assert "balance" in vo_fields
    assert "name" not in vo_fields
    assert "age" not in vo_fields
    assert all(isinstance(field, ValueObject) for field in vo_fields.values())
