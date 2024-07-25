import pytest

from protean.core.aggregate import BaseAggregate, element_to_fact_event
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import (
    Date,
    Float,
    HasMany,
    HasOne,
    Integer,
    List,
    String,
    ValueObject,
)
from protean.reflection import declared_fields


class Shipment(BaseAggregate):
    tracking_id = String(max_length=50)
    order = HasOne("Order")


class Order(BaseEntity):
    ordered_on = Date()
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_id = String(max_length=50)
    quantity = Integer()
    price = Float()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Shipment)
    test_domain.register(Order, part_of=Shipment)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.init(traverse=False)


@pytest.fixture
def event_cls():
    return element_to_fact_event(Shipment)


def test_fact_event_class_generation(event_cls):
    assert event_cls.__name__ == "ShipmentFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert len(declared_fields(event_cls)) == 3

    assert all(
        field_name in declared_fields(event_cls)
        for field_name in ["tracking_id", "order", "id"]
    )


def test_order_is_a_value_object(event_cls):
    order_field = declared_fields(event_cls)["order"]

    assert isinstance(order_field, ValueObject)
    assert order_field.value_object_cls.__name__ == "OrderValueObject"


def test_order_items_is_a_list_of_value_objects(event_cls):
    order_field = declared_fields(event_cls)["order"]
    order_items_field = declared_fields(order_field._value_object_cls)["items"]

    assert isinstance(order_items_field, List)
    assert isinstance(order_items_field.content_type, ValueObject)
    assert (
        order_items_field.content_type._value_object_cls.__name__
        == "OrderItemValueObject"
    )


def test_order_value_object_fields(event_cls):
    order_field = declared_fields(event_cls)["order"]
    order_cls = order_field._value_object_cls

    assert len(declared_fields(order_cls)) == 3
    assert all(
        field_name in declared_fields(order_cls)
        for field_name in ["ordered_on", "items", "id"]
    )


def test_order_items_value_object_fields(event_cls):
    order_field = declared_fields(event_cls)["order"]
    order_items_field = declared_fields(order_field._value_object_cls)["items"]
    order_items_vo_cls = order_items_field.content_type._value_object_cls

    assert len(declared_fields(order_items_vo_cls)) == 4
    assert all(
        field_name in declared_fields(order_items_vo_cls)
        for field_name in ["product_id", "quantity", "price", "id"]
    )
