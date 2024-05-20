import pytest

from datetime import datetime, timedelta

from protean import BaseAggregate, BaseEntity
from protean.fields import Date, String, HasMany
from protean.reflection import declared_fields


class Customer(BaseAggregate):
    name = String(max_length=50)
    orders = HasMany("Order")
    addresses = HasMany("Address")


class Order(BaseEntity):
    ordered_on = Date()

    class Meta:
        part_of = Customer


class Address(BaseEntity):
    street = String(max_length=50)
    city = String(max_length=50)
    state = String(max_length=50)
    zip_code = String(max_length=10)

    class Meta:
        part_of = Customer


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(Order)
    test_domain.register(Address)
    test_domain.init(traverse=False)


def test_multiple_has_many_associations():
    assert declared_fields(Customer)["orders"].__class__.__name__ == "HasMany"
    assert declared_fields(Customer)["orders"].field_name == "orders"
    assert declared_fields(Customer)["orders"].to_cls == Order

    assert declared_fields(Customer)["addresses"].__class__.__name__ == "HasMany"
    assert declared_fields(Customer)["addresses"].field_name == "addresses"
    assert declared_fields(Customer)["addresses"].to_cls == Address


def test_customer_basic_structure_with_multiple_items_in_associations():
    order1 = Order(ordered_on=datetime.today().date())
    order2 = Order(ordered_on=datetime.today().date() - timedelta(days=1))
    address1 = Address(
        street="123 Main St", city="Anytown", state="NY", zip_code="12345"
    )
    address2 = Address(
        street="456 Elm St", city="Anytown", state="NY", zip_code="12345"
    )
    customer = Customer(
        name="John Doe", orders=[order1, order2], addresses=[address1, address2]
    )

    assert len(customer.orders) == 2
    assert customer.orders[0] == order1
    assert customer.orders[0].customer_id == customer.id
    assert customer.orders[0].customer == customer

    assert len(customer.addresses) == 2
    assert customer.addresses[0] == address1
    assert customer.addresses[0].customer_id == customer.id
    assert customer.addresses[0].customer == customer


def test_basic_persistence(test_domain):
    order1 = Order(ordered_on=datetime.today().date())
    order2 = Order(ordered_on=datetime.today().date() - timedelta(days=1))
    address1 = Address(
        street="123 Main St", city="Anytown", state="NY", zip_code="12345"
    )
    address2 = Address(
        street="456 Elm St", city="Anytown", state="NY", zip_code="12345"
    )
    customer = Customer(
        name="John Doe", orders=[order1, order2], addresses=[address1, address2]
    )

    assert customer.id is not None
    assert customer.orders[0].id is not None
    assert customer.orders[1].id is not None
    assert customer.addresses[0].id is not None
    assert customer.addresses[1].id is not None
    assert customer.orders[0].customer_id == customer.id
    assert customer.orders[1].customer_id == customer.id
    assert customer.addresses[0].customer_id == customer.id
    assert customer.addresses[1].customer_id == customer.id

    test_domain.repository_for(Customer).add(customer)

    fetched_customer = test_domain.repository_for(Customer).get(customer.id)

    assert fetched_customer.name == "John Doe"
    assert len(fetched_customer.orders) == 2
    assert fetched_customer.orders[0].ordered_on == datetime.today().date()
    assert fetched_customer.orders[1].ordered_on == datetime.today().date() - timedelta(
        days=1
    )
    assert len(fetched_customer.addresses) == 2
    assert fetched_customer.addresses[0].street == "123 Main St"
    assert fetched_customer.addresses[1].street == "456 Elm St"
