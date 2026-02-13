import pytest

from protean.core.aggregate import BaseAggregate, element_to_fact_event
from protean.core.entity import BaseEntity
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.fields import Date, HasMany, List, String, ValueObject
from protean.utils.reflection import declared_fields


class Customer(BaseAggregate):
    name = String(max_length=50)
    orders = HasMany("Order")
    addresses = HasMany("Address")


class Order(BaseEntity):
    ordered_on = Date()


class Address(BaseEntity):
    street = String(max_length=50)
    city = String(max_length=50)
    state = String(max_length=50)
    zip_code = String(max_length=10)


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

    assert isinstance(orders_field, List)
    assert isinstance(orders_field.content_type, ValueObject)
    assert orders_field.content_type._value_object_cls.__name__ == "OrderValueObject"


def test_addresses_is_a_list_of_value_objects(event_cls):
    addresses_field = declared_fields(event_cls)["addresses"]

    assert isinstance(addresses_field, List)
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
