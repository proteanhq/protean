import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import HasOne, List, ValueObject


class Address(BaseValueObject):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None


class Customer(BaseEntity):
    name: str
    email: str
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
