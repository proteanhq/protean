import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.entity import _LegacyBaseEntity as BaseEntity
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.fields import HasOne, List, String, ValueObject


class Address(BaseValueObject):
    street = String(max_length=100)
    city = String(max_length=25)
    state = String(max_length=25)
    country = String(max_length=25)


class Customer(BaseEntity):
    name = String(max_length=50, required=True)
    email = String(max_length=254, required=True)
    addresses = List(content_type=ValueObject(Address))


# Aggregate that encloses Customer Entity
class Order(BaseAggregate):
    customer = HasOne(Customer)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(Customer, part_of=Order)
    test_domain.register(Address)
    test_domain.init(traverse=False)


def test_that_list_of_value_objects_can_be_assigned_during_initialization(test_domain):
    customer = Customer(
        name="John Doe",
        email="john@doe.com",
        addresses=[
            Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
            Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
        ],
    )

    assert customer is not None
    assert customer.addresses == [
        Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
        Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
    ]


def test_that_entity_with_list_of_value_objects_is_persisted_and_retrieved(test_domain):
    order = Order(
        customer=Customer(
            name="John Doe",
            email="john@doe.com",
            addresses=[
                Address(
                    street="123 Main St", city="Anytown", state="CA", country="USA"
                ),
                Address(
                    street="321 Side St", city="Anytown", state="CA", country="USA"
                ),
            ],
        )
    )

    test_domain.repository_for(Order).add(order)

    retrieved_order = test_domain.repository_for(Order).get(order.id)

    assert retrieved_order is not None
    assert retrieved_order.customer is not None
    assert retrieved_order.customer.id == order.customer.id
    assert retrieved_order.customer.addresses == [
        Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
        Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
    ]


def test_that_a_value_object_can_be_updated(test_domain):
    customer = Customer(
        name="John Doe",
        email="john@doe.com",
        addresses=[
            Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
            Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
        ],
    )

    customer.addresses.append(
        Address(street="123 Side St", city="Anytown", state="CA", country="USA")
    )

    assert len(customer.addresses) == 3
    assert customer.addresses == [
        Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
        Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
        Address(street="123 Side St", city="Anytown", state="CA", country="USA"),
    ]


def test_that_a_persisted_entity_with_list_of_value_objects_can_be_updated(test_domain):
    order = Order(
        customer=Customer(
            name="John Doe",
            email="john@doe.com",
            addresses=[
                Address(
                    street="123 Main St", city="Anytown", state="CA", country="USA"
                ),
                Address(
                    street="321 Side St", city="Anytown", state="CA", country="USA"
                ),
            ],
        )
    )

    test_domain.repository_for(Order).add(order)

    retrieved_order = test_domain.repository_for(Order).get(order.id)

    # [].append does not work.
    retrieved_order.customer.addresses = [
        Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
        Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
        Address(street="456 Side St", city="Anytown", state="CA", country="USA"),
    ]
    assert len(retrieved_order.customer.addresses) == 3

    test_domain.repository_for(Order).add(retrieved_order)

    retrieved_order = test_domain.repository_for(Order).get(order.id)

    assert len(retrieved_order.customer.addresses) == 3
