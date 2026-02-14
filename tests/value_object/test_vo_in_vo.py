import pytest

from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject
from protean.utils.reflection import fields


class Address(BaseValueObject):
    street: String(max_length=50)
    city: String(max_length=25)
    state: String(max_length=25)
    zip_code: String(max_length=10)


class Contact(BaseValueObject):
    email: String(max_length=255)
    phone_number: String(max_length=255)
    address = ValueObject(Address)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Contact)
    test_domain.register(Address)
    test_domain.init(traverse=False)


def test_contact_has_address_vo():
    assert "address" in fields(Contact)


def test_outer_vo_initialization():
    contact = Contact(
        email="john.doe@example.com",
        phone_number="123-456-7890",
        address=Address(
            street="123 Main Street", city="Anytown", state="CA", zip_code="12345"
        ),
    )

    assert contact is not None
    assert contact.email == "john.doe@example.com"
    assert contact.address == Address(
        street="123 Main Street", city="Anytown", state="CA", zip_code="12345"
    )
    assert contact.address.street == "123 Main Street"


def test_vo_initialization_with_nested_dict():
    contact = Contact(
        email="john.doe@example.com",
        phone_number="123-456-7890",
        address={
            "street": "123 Main Street",
            "city": "Anytown",
            "state": "CA",
            "zip_code": "12345",
        },
    )

    assert contact is not None
    assert contact.email == "john.doe@example.com"
    assert contact.address == Address(
        street="123 Main Street", city="Anytown", state="CA", zip_code="12345"
    )
