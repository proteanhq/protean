import pytest

from protean import BaseValueObject
from protean.fields import String, ValueObject
from protean.reflection import fields


class Address(BaseValueObject):
    street = String(max_length=50)
    city = String(max_length=25)
    state = String(max_length=25)
    zip_code = String(max_length=10)


class Contact(BaseValueObject):
    email = String(max_length=255)
    phone_number = String(max_length=255)
    address = ValueObject(Address)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Contact)
    test_domain.register(Address)
    test_domain.init(traverse=False)


def test_contact_has_address_vo():
    assert isinstance(fields(Contact)["address"], ValueObject)
    assert hasattr(Contact, "address")


def test_outer_vo_initialization():
    contact = Contact(
        email="<EMAIL>",
        phone_number="123-456-7890",
        address=Address(
            street="123 Main Street", city="Anytown", state="CA", zip_code="12345"
        ),
    )

    assert contact is not None
