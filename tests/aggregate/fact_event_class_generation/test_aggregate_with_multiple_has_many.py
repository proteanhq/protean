from datetime import date

import pytest

from protean.core.aggregate import BaseAggregate, element_to_fact_event
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasMany, ValueObject
from protean.fields.basic import ValueObjectList
from protean.utils.reflection import declared_fields


class Customer(BaseAggregate):
    name: str | None = None
    orders = HasMany("Order")
    addresses = HasMany("Address")


class Order(BaseEntity):
    ordered_on: date | None = None


class Address(BaseEntity):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(Order, part_of=Customer)
    test_domain.register(Address, part_of=Customer)
    test_domain.init(traverse=False)


@pytest.fixture
def event_cls():
    return element_to_fact_event(Customer)


def test_fact_event_class_generation(event_cls):
    assert event_cls.__name__ == "CustomerFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert len(declared_fields(event_cls)) == 4

    assert all(
        field_name in declared_fields(event_cls)
        for field_name in ["name", "orders", "addresses", "id"]
    )


def test_orders_is_a_list_of_value_objects(event_cls):
    orders_field = declared_fields(event_cls)["orders"]

    assert isinstance(orders_field, ValueObjectList)
    assert isinstance(orders_field.content_type, ValueObject)
    assert orders_field.content_type._value_object_cls.__name__ == "OrderValueObject"


def test_addresses_is_a_list_of_value_objects(event_cls):
    addresses_field = declared_fields(event_cls)["addresses"]

    assert isinstance(addresses_field, ValueObjectList)
    assert isinstance(addresses_field.content_type, ValueObject)
    assert (
        addresses_field.content_type._value_object_cls.__name__ == "AddressValueObject"
    )


def test_order_value_object_fields(event_cls):
    orders_field = declared_fields(event_cls)["orders"]
    order_vo_cls = orders_field.content_type._value_object_cls

    assert len(declared_fields(order_vo_cls)) == 2
    assert all(
        field_name in declared_fields(order_vo_cls)
        for field_name in ["ordered_on", "id"]
    )


def test_address_value_object_fields(event_cls):
    addresses_field = declared_fields(event_cls)["addresses"]
    address_vo_cls = addresses_field.content_type._value_object_cls

    assert len(declared_fields(address_vo_cls)) == 5
    assert all(
        field_name in declared_fields(address_vo_cls)
        for field_name in ["street", "city", "state", "zip_code", "id"]
    )
