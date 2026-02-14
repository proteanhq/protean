# Test that limit option provided in Entity config is respected

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import Date, Float, HasMany, Integer, String


class Order(BaseAggregate):
    ordered_on = Date()
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_id = String(max_length=50)
    quantity = Integer()
    price = Float()


def test_entity_query_limit_is_100_by_default(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)

    assert test_domain.repository_for(OrderItem)._dao.query._limit == 100


def test_entity_query_limit_can_be_explicitly_set_in_entity_config(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order, limit=500)

    assert test_domain.repository_for(OrderItem)._dao.query._limit == 500


def test_entity_query_limit_is_unlimited_when_limit_is_set_to_none(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order, limit=None)

    assert test_domain.repository_for(OrderItem)._dao.query._limit is None


def test_entity_query_limit_is_unlimited_when_limit_is_set_to_negative_value(
    test_domain,
):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order, limit=-1)

    assert test_domain.repository_for(OrderItem)._dao.query._limit is None
