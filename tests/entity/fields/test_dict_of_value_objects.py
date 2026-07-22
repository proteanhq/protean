import json

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Dict, HasOne, String, ValueObject


class Address(BaseValueObject):
    street: String(max_length=100)
    city: String(max_length=25)


class Customer(BaseEntity):
    name: String(max_length=50, required=True)
    email: String(max_length=254, required=True)
    addresses: Dict(value_type=ValueObject(Address))


# Aggregate that encloses the Customer entity, for persistence round-trips.
class Order(BaseAggregate):
    customer = HasOne(Customer)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(Customer, part_of=Order)
    test_domain.register(Address)
    test_domain.init(traverse=False)


def test_that_a_dict_of_value_objects_can_be_assigned_during_initialization():
    customer = Customer(
        name="John Doe",
        email="john@doe.com",
        addresses={
            "home": Address(street="123 Main St", city="Anytown"),
            "work": Address(street="321 Side St", city="Anytown"),
        },
    )

    assert customer is not None
    assert customer.addresses["home"] == Address(street="123 Main St", city="Anytown")
    assert customer.addresses["work"] == Address(street="321 Side St", city="Anytown")


def test_that_raw_dict_values_are_reconstructed_into_value_objects():
    # Values supplied as raw dicts (as an adapter returns on load) are
    # reconstructed into value-object instances.
    customer = Customer(
        name="Jane",
        email="jane@doe.com",
        addresses={"home": {"street": "1 A St", "city": "Town"}},
    )

    assert isinstance(customer.addresses["home"], Address)
    assert customer.addresses["home"].city == "Town"


def test_that_a_dict_of_value_objects_serializes_to_plain_dicts():
    customer = Customer(
        name="John",
        email="j@d.com",
        addresses={"home": Address(street="1 A St", city="Town")},
    )

    data = customer.to_dict()

    assert data["addresses"] == {"home": {"street": "1 A St", "city": "Town"}}
    json.dumps(data)  # must not raise


def test_that_an_entity_with_a_dict_of_value_objects_is_persisted_and_retrieved(
    test_domain,
):
    order = Order(
        customer=Customer(
            name="John Doe",
            email="john@doe.com",
            addresses={
                "home": Address(street="123 Main St", city="Anytown"),
                "work": Address(street="321 Side St", city="Anytown"),
            },
        )
    )

    test_domain.repository_for(Order).add(order)
    retrieved = test_domain.repository_for(Order).get(order.id)

    assert retrieved.customer.addresses == {
        "home": Address(street="123 Main St", city="Anytown"),
        "work": Address(street="321 Side St", city="Anytown"),
    }


def test_that_a_persisted_dict_of_value_objects_can_be_updated(test_domain):
    order = Order(
        customer=Customer(
            name="John Doe",
            email="john@doe.com",
            addresses={"home": Address(street="123 Main St", city="Anytown")},
        )
    )
    test_domain.repository_for(Order).add(order)

    retrieved = test_domain.repository_for(Order).get(order.id)
    retrieved.customer.addresses = {
        "home": Address(street="123 Main St", city="Anytown"),
        "work": Address(street="456 Side St", city="Anytown"),
    }
    test_domain.repository_for(Order).add(retrieved)

    retrieved = test_domain.repository_for(Order).get(order.id)
    assert len(retrieved.customer.addresses) == 2
    assert retrieved.customer.addresses["work"] == Address(
        street="456 Side St", city="Anytown"
    )


def test_that_value_type_must_be_a_value_object():
    # The typed dict is value-object-only; a non-VO value type is rejected.
    with pytest.raises(ValidationError):
        Dict(value_type=String())


def test_is_value_object_dict_helper():
    # The predicate the SQLAlchemy adapter uses to decide whether a dict field
    # holds value objects (and so must be serialized before storage).
    from protean.adapters.repository.sqlalchemy import _is_value_object_dict
    from protean.utils.reflection import fields

    vo_dict_field = fields(Customer)["addresses"]
    home = Address(street="1 A St", city="Town")

    assert _is_value_object_dict(vo_dict_field, {"home": home}) is True
    assert _is_value_object_dict(vo_dict_field, {}) is False  # empty dict
    assert _is_value_object_dict(vo_dict_field, [home]) is False  # not a dict
    assert _is_value_object_dict(fields(Customer)["name"], {"x": 1}) is False  # no ct

    class _StrTyped:
        content_type = str

    # A typed-but-non-VO content type is not a value-object dict.
    assert _is_value_object_dict(_StrTyped(), {"a": 1}) is False
