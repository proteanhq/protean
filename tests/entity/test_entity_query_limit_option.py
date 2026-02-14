# Test that limit provided in Entity options is respected

from datetime import date

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany


class Order(BaseAggregate):
    ordered_on: date | None = None
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_id: str | None = None
    quantity: int | None = None
    price: float | None = None


def test_entity_query_limit_is_1000_by_default(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)

    assert Order.meta_.limit == 100
    assert OrderItem.meta_.limit == 100


def test_entity_query_limit_can_be_explicitly_set_in_entity_config(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order, limit=5000)

    assert Order.meta_.limit == 100
    assert OrderItem.meta_.limit == 5000


def test_entity_query_limit_can_be_unlimited(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order, limit=None)

    assert Order.meta_.limit == 100
    assert OrderItem.meta_.limit is None


def test_entity_query_limit_is_unlimited_when_limit_is_set_to_negative_value(
    test_domain,
):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order, limit=-1)

    assert Order.meta_.limit == 100
    assert OrderItem.meta_.limit is None
