"""An empty value that is not ``None`` on an optional field with no default
goes on to the field's cast instead of being returned as is."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject, ValueObjectList


class Address(BaseValueObject):
    street = String()


class Customer(BaseAggregate):
    address = ValueObject(Address)
    addresses = ValueObjectList(content_type=ValueObject(Address))


def test_empty_dict_on_value_object_field_is_cast_to_a_value_object(test_domain):
    test_domain.register(Customer)
    test_domain.register(Address, part_of=Customer)
    test_domain.init(traverse=False)

    customer = Customer(address={})

    assert customer.address == Address(street=None)


def test_empty_tuple_on_value_object_list_field_is_rejected_by_the_cast(
    test_domain,
):
    test_domain.register(Customer)
    test_domain.register(Address, part_of=Customer)
    test_domain.init(traverse=False)

    with pytest.raises(ValidationError) as exc:
        Customer(addresses=())

    assert exc.value.messages == {"addresses": ['"()" value must be of list type.']}
