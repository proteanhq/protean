import pytest

from protean.core.value_object import BaseValueObject, _LegacyBaseValueObject
from protean.fields import String, ValueObject
from protean.utils.reflection import fields


class Address(BaseValueObject):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None


# Contact uses _LegacyBaseValueObject because the Pydantic-based BaseValueObject
# does not yet support ValueObject descriptors (VO-in-VO embedding).
class Contact(_LegacyBaseValueObject):
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
    assert contact.address_street == "123 Main Street"


def test_vo_initialization_with_attributes():
    contact = Contact(
        email="john.doe@example.com",
        phone_number="123-456-7890",
        address_street="123 Main Street",
        address_city="Anytown",
        address_state="CA",
        address_zip_code="12345",
    )

    assert contact is not None
    assert contact.email == "john.doe@example.com"
    assert contact.address == Address(
        street="123 Main Street", city="Anytown", state="CA", zip_code="12345"
    )
