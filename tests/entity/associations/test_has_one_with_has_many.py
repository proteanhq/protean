from datetime import date, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, HasOne
from protean.utils.reflection import declared_fields


class Shipment(BaseAggregate):
    tracking_id: str | None = None
    order = HasOne("Order")


class Order(BaseEntity):
    ordered_on: date | None = None
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_id: str | None = None
    quantity: int | None = None
    price: float | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Shipment)
    test_domain.register(Order, part_of=Shipment)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.init(traverse=False)


def test_1st_level_associations():
    assert declared_fields(Shipment)["order"].__class__.__name__ == "HasOne"
    assert declared_fields(Shipment)["order"].field_name == "order"
    assert declared_fields(Shipment)["order"].to_cls == Order

    assert declared_fields(Order)["items"].__class__.__name__ == "HasMany"
    assert declared_fields(Order)["items"].field_name == "items"
    assert declared_fields(Order)["items"].to_cls == OrderItem


def test_shipment_basic_structure():
    items = [
        OrderItem(product_id="1", quantity=2, price=10.0),
        OrderItem(product_id="2", quantity=3, price=15.0),
    ]
    order = Order(ordered_on=datetime.today().date(), items=items)
    shipment = Shipment(tracking_id="123456", order=order)

    assert shipment.order == order
    assert order.shipment_id == shipment.id
    assert len(order.items) == 2
    assert order.items[0].order_id == order.id
    assert order.items[1].order_id == order.id


@pytest.fixture
def shipment(test_domain):
    items = [
        OrderItem(product_id="1", quantity=2, price=10.0),
        OrderItem(product_id="2", quantity=3, price=15.0),
    ]
    order = Order(ordered_on=datetime.today().date(), items=items)
    shipment = Shipment(tracking_id="123456", order=order)

    test_domain.repository_for(Shipment).add(shipment)

    return test_domain.repository_for(Shipment).get(shipment.id)


def test_switch_1st_level_has_one_entity(test_domain, shipment):
    shipment.order = Order(
        ordered_on=datetime.today().date() - timedelta(days=1),
        items=[
            OrderItem(product_id="3", quantity=4, price=20.0),
            OrderItem(product_id="4", quantity=5, price=25.0),
        ],
    )

    test_domain.repository_for(Shipment).add(shipment)

    # Reload the shipment from the repository
    reloaded_shipment = test_domain.repository_for(Shipment).get(shipment.id)

    assert reloaded_shipment.order.ordered_on == datetime.today().date() - timedelta(
        days=1
    )
    assert len(reloaded_shipment.order.items) == 2
    assert reloaded_shipment.order.items[0].product_id == "3"
    assert reloaded_shipment.order.items[1].product_id == "4"


def test_direct_update_1st_level_has_one_entity(test_domain, shipment):
    shipment.order.ordered_on = datetime.today().date() - timedelta(days=2)

    test_domain.repository_for(Shipment).add(shipment)

    # Reload the shipment from the repository
    reloaded_shipment = test_domain.repository_for(Shipment).get(shipment.id)

    assert reloaded_shipment.order.ordered_on == datetime.today().date() - timedelta(
        days=2
    )


def test_add_2nd_level_has_many_entities(test_domain, shipment):
    shipment.order.items = [
        OrderItem(product_id="3", quantity=4, price=20.0),
        OrderItem(product_id="4", quantity=5, price=25.0),
    ]

    test_domain.repository_for(Shipment).add(shipment)

    # Reload the shipment from the repository
    reloaded_shipment = test_domain.repository_for(Shipment).get(shipment.id)

    assert len(reloaded_shipment.order.items) == 4
    assert reloaded_shipment.order.items[2].product_id == "3"
    assert reloaded_shipment.order.items[3].product_id == "4"


def test_remove_a_2nd_level_has_many_entity(test_domain, shipment):
    shipment.order.remove_items(shipment.order.items[0])

    test_domain.repository_for(Shipment).add(shipment)

    # Reload the shipment from the repository
    reloaded_shipment = test_domain.repository_for(Shipment).get(shipment.id)

    assert len(reloaded_shipment.order.items) == 1
    assert reloaded_shipment.order.items[0].product_id == "2"
