import pytest

from protean import BaseAggregate, BaseEntity, BaseValueObject
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


@pytest.mark.postgresql
def test_persisting_and_retrieving_list_of_value_objects(test_domain):
    test_domain.register(Order)
    test_domain.register(Customer, part_of=Order)
    test_domain.register(Address)
    test_domain.init(traverse=False)

    order = Order(
        customer=Customer(
            name="John",
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
