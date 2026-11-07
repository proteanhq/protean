"""A ``ValueObjectList`` whose value object is named by a string is resolved
when the domain initializes."""

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject, ValueObjectList
from protean.utils.reflection import declared_fields


def _customer_cls():
    # Resolution swaps the string for the class on the descriptor itself, so
    # each test needs its own descriptor to stay independent of test order.
    class Customer(BaseAggregate):
        name = String()
        addresses = ValueObjectList(content_type=ValueObject("Address"))

    return Customer


class Address(BaseValueObject):
    street = String()


def test_string_value_object_name_is_pending_until_init(test_domain):
    Customer = _customer_cls()
    test_domain.register(Customer)

    content_type = declared_fields(Customer)["addresses"].content_type
    assert test_domain._pending_class_resolutions["Address"] == [
        ("ValueObject", (content_type, Customer))
    ]


def test_string_value_object_name_resolves_to_the_registered_class(test_domain):
    Customer = _customer_cls()
    test_domain.register(Customer)
    test_domain.register(Address, part_of=Customer)
    test_domain.init(traverse=False)

    content_type = declared_fields(Customer)["addresses"].content_type
    assert content_type.value_object_cls is Address
    assert "Address" not in test_domain._pending_class_resolutions

    customer = Customer(name="John", addresses=[{"street": "1 Main St"}])
    assert customer.addresses == [Address(street="1 Main St")]
