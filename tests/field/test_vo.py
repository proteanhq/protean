import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import String, ValueObject
from protean.utils.reflection import fields


def test_value_object_associated_class(test_domain):
    class Address(BaseValueObject):
        street_address = String()

    class User(BaseAggregate):
        email = String()
        address = ValueObject(Address)

    assert fields(User)["address"].value_object_cls == Address


def test_value_object_to_cls_is_always_a_base_value_object_subclass(test_domain):
    class Address(BaseEntity):
        street_address = String()

    with pytest.raises(IncorrectUsageError) as exc:

        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

    assert exc.value.args[0] == (
        "`Address` is not a valid Value Object and cannot be embedded in a Value Object field"
    )
