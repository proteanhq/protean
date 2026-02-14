from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError
from protean.fields import Date, Float, HasMany, Integer, String


class Order(BaseAggregate):
    ordered_on = Date()
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_id = String(max_length=50)
    quantity = Integer()
    price = Float()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.init(traverse=False)


def test_get():
    order = Order(
        ordered_on=datetime.today().date(),
        items=[
            OrderItem(product_id="1", quantity=2, price=10.0),
            OrderItem(product_id="2", quantity=3, price=15.0),
            OrderItem(product_id="3", quantity=2, price=20.0),
        ],
    )

    assert order.get_one_from_items(product_id="1").id == order.items[0].id

    with pytest.raises(ObjectNotFoundError):
        order.get_one_from_items(product_id="4")

    with pytest.raises(TooManyObjectsError):
        order.get_one_from_items(quantity=2)


def test_filtering():
    order = Order(
        ordered_on=datetime.today().date(),
        items=[
            OrderItem(product_id="1", quantity=2, price=10.0),
            OrderItem(product_id="2", quantity=3, price=15.0),
            OrderItem(product_id="3", quantity=2, price=20.0),
        ],
    )

    filtered_item = order.filter_items(product_id="1")
    assert len(filtered_item) == 1
    assert filtered_item[0].id == order.items[0].id

    filtered_items = order.filter_items(quantity=2)
    assert len(filtered_items) == 2
    assert filtered_items[0].id == order.items[0].id
    assert filtered_items[1].id == order.items[2].id

    filtered_items = order.filter_items(quantity=2, price=20.0)
    assert len(filtered_items) == 1
    assert filtered_items[0].id == order.items[2].id

    filtered_items = order.filter_items(quantity=3, price=40.0)
    assert len(filtered_items) == 0
