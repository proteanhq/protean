from datetime import date, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany
from protean.utils.reflection import declared_fields


class Customer(BaseAggregate):
    name: str | None = None
    orders = HasMany("Order")


class Order(BaseEntity):
    ordered_on: date | None = None
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_id: str
    quantity: float | None = None
    price: float | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(Order, part_of=Customer)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.init(traverse=False)


def test_1st_level_associations():
    assert declared_fields(Order)["items"].__class__.__name__ == "HasMany"
    assert declared_fields(Order)["items"].field_name == "items"
    assert declared_fields(Order)["items"].to_cls == OrderItem


def test_customers_basic_structure():
    items = [
        OrderItem(id="item-1", product_id="product-1", quantity=2, price=10.0),
        OrderItem(id="item-2", product_id="product-2", quantity=3, price=15.0),
    ]
    order = Order(id="order-1", ordered_on=datetime.today().date(), items=items)
    customer = Customer(
        id="customer-1",
        name="John Doe",
        orders=[order],
    )

    len(customer.orders) == 1
    customer.orders[0] == order
    customer.orders[0].customer_id == customer.id
    customer.orders[0].customer == customer
    len(customer.orders[0].items) == 2
    customer.orders[0].items[0] == items[0]
    customer.orders[0].items[0].order_id == order.id
    customer.orders[0].items[0].order == order


@pytest.fixture
def customer(test_domain):
    # Create a customer, with an order and multiple order items
    items = [
        OrderItem(id="item-1", product_id="product-1", quantity=2, price=10.0),
        OrderItem(id="item-2", product_id="product-2", quantity=3, price=15.0),
    ]
    order = Order(id="order-1", ordered_on=datetime.today().date(), items=items)
    customer = Customer(
        id="customer-1",
        name="John Doe",
        orders=[order],
    )

    # Persist the customer
    test_domain.repository_for(Customer).add(customer)

    # return refreshed customer
    return test_domain.repository_for(Customer).get(customer.id)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestEntityAssociationsAdd:
    def test_all_associations_are_persisted_on_direct_initialization(self, customer):
        assert len(customer.orders) == 1
        assert customer.orders[0].ordered_on == datetime.today().date()
        customer.orders[0].customer_id == customer.id
        customer.orders[0].customer == customer

        assert len(customer.orders[0].items) == 2
        item1 = next(item for item in customer.orders[0].items if item.id == "item-1")
        assert item1.product_id == "product-1"
        assert item1.order_id == customer.orders[0].id
        assert item1.order == customer.orders[0]

    def test_all_associations_are_persisted_on_1st_level_nested_entity_addition(
        self, test_domain, customer
    ):
        customer.add_orders(
            Order(
                id="order-2",
                ordered_on=datetime.today().date(),
                items=[
                    OrderItem(
                        id="item-3", product_id="product-3", quantity=1, price=20.0
                    ),
                ],
            )
        )

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        # Ensure new order is added
        assert len(refreshed_customer.orders) == 2
        new_order = next(
            order for order in refreshed_customer.orders if order.id == "order-2"
        )
        assert new_order.items[0].product_id == "product-3"
        assert new_order.items[0].order_id == new_order.id
        assert new_order.items[0].order == new_order

        # Ensure old order item is intact
        assert len(refreshed_customer.orders[0].items) == 2

    def test_all_associations_are_persisted_on_2nd_level_nested_entity_addition(
        self, test_domain, customer
    ):
        customer.orders[0].add_items(
            OrderItem(id="item-4", product_id="product-4", quantity=4, price=20.0)
        )

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert len(refreshed_customer.orders[0].items) == 3


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestEntityAssociationsUpdate:
    def test_associations_updates_are_persisted_on_1st_level_nested_entity_updates(
        self, test_domain, customer
    ):
        customer.orders[0].ordered_on = datetime.today().date() - timedelta(days=1)

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert refreshed_customer.orders[
            0
        ].ordered_on == datetime.today().date() - timedelta(days=1)

    def test_associations_updates_are_persisted_on_2nd_level_nested_entity_updates(
        self, test_domain, customer
    ):
        customer.orders[0].items[0].quantity = 15

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert refreshed_customer.orders[0].items[0].quantity == 15

    def test_associations_updates_are_persisted_on_1st_level_nested_entity_object_update(
        self, test_domain, customer
    ):
        order = customer.orders[0]
        order.ordered_on = datetime.today().date() - timedelta(days=1)
        customer.add_orders(order)

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert refreshed_customer.orders[
            0
        ].ordered_on == datetime.today().date() - timedelta(days=1)

    def test_associations_updates_are_persisted_on_2nd_level_nested_entity_object_update(
        self, test_domain, customer
    ):
        order_item = customer.orders[0].items[0]
        order_item.quantity = 15
        customer.orders[0].add_items(order_item)

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert refreshed_customer.orders[0].items[0].quantity == 15


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestEntityAssociationsRemoval:
    def test_associations_removal_is_persisted_on_1st_level_nested_entity_removal(
        self, test_domain, customer
    ):
        customer.remove_orders(customer.orders[0])

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert len(refreshed_customer.orders) == 0

    def test_associations_removal_is_persisted_on_2nd_level_nested_entity_removal(
        self, test_domain, customer
    ):
        customer.orders[0].remove_items(customer.orders[0].items[0])

        test_domain.repository_for(Customer).add(customer)

        # Retrieve the customer from the repository
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)

        assert len(refreshed_customer.orders[0].items) == 1
