import pytest

from protean import BaseAggregate, BaseEntity, BaseEvent
from protean.core.aggregate import element_to_fact_event
from protean.fields import Date, HasMany, List, String, ValueObject
from protean.reflection import declared_fields


class Customer(BaseAggregate):
    name = String(max_length=50)
    orders = HasMany("Order")


class Order(BaseEntity):
    ordered_on = Date()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(Order, part_of=Customer)
    test_domain.init(traverse=False)


@pytest.fixture
def event_cls():
    return element_to_fact_event(Customer)


def test_fact_event_class_generation(event_cls):
    assert event_cls.__name__ == "CustomerFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert len(declared_fields(event_cls)) == 3

    assert all(
        field_name in declared_fields(event_cls)
        for field_name in ["name", "orders", "id"]
    )


def test_orders_is_a_list_of_value_objects(event_cls):
    orders_field = declared_fields(event_cls)["orders"]

    assert isinstance(orders_field, List)
    assert isinstance(orders_field.content_type, ValueObject)
    assert orders_field.content_type._value_object_cls.__name__ == "OrderValueObject"


def test_order_value_object_fields(event_cls):
    orders_field = declared_fields(event_cls)["orders"]
    order_vo_cls = orders_field.content_type._value_object_cls

    assert len(declared_fields(order_vo_cls)) == 2
    assert all(
        field_name in declared_fields(order_vo_cls)
        for field_name in ["ordered_on", "id"]
    )
