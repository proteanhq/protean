import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.entity import _LegacyBaseEntity as BaseEntity
from protean.fields import Float, HasMany, Integer, String


class OrderItem(BaseEntity):
    product_id = String(max_length=50)
    quantity = Integer()
    price = Float()


class Order(BaseAggregate):
    items = HasMany(OrderItem)


@pytest.mark.database
class TestQuerySetLimit:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)

    def test_default_queryset_limit_is_applied(self, test_domain):
        # Create an order with 1001 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem)._dao.query._limit == 100

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are limited to 100 by default
        assert len(order.items) == 100

        # Verify that the order items are not limited when limit is set to None
        assert (
            len(test_domain.repository_for(OrderItem)._dao.query.limit(None).all())
            == 101
        )

    def test_no_queryset_limit_is_applied_if_limit_is_set_to_none(self, test_domain):
        test_domain.register(OrderItem, part_of=Order, limit=None)

        # Create an order with 1001 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem)._dao.query._limit is None

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are not limited when limit is set to None
        assert len(order.items) == 101

    def test_queryset_limit_is_applied_if_limit_is_set(self, test_domain):
        test_domain.register(OrderItem, part_of=Order, limit=10)

        # Create an order with 1001 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem)._dao.query._limit == 10

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are limited to 10
        assert len(order.items) == 10

    def test_no_queryset_limit_is_applied_if_limit_is_set_to_negative_value(
        self, test_domain
    ):
        test_domain.register(OrderItem, part_of=Order, limit=-1)

        # Create an order with 1001 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem)._dao.query._limit is None

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are not limited when limit is set to None
        assert len(order.items) == 101
