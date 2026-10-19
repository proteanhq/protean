"""A projection ``ValueObject`` field in the typed-annotation style.

``address: Address | None = ValueObject(Address)`` must behave like
``address = ValueObject(Address)``: a descriptor with flattened shadow fields.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String, ValueObject
from protean.utils.reflection import attributes, declared_fields


class Address(BaseValueObject):
    street: str | None = String()
    city: str | None = String()


class AddressView(BaseProjection):
    customer_id: str = Identifier(identifier=True)
    address: Address | None = ValueObject(Address)


class QuotedAddressView(BaseProjection):
    customer_id: str = Identifier(identifier=True)
    address: "Address | None" = ValueObject("Address")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Address)
    test_domain.register(AddressView)
    test_domain.register(QuotedAddressView)
    test_domain.init(traverse=False)


@pytest.mark.parametrize("view_cls", [AddressView, QuotedAddressView])
class TestTypedAnnotationValueObject:
    def test_field_is_a_value_object_descriptor(self, view_cls) -> None:
        assert isinstance(declared_fields(view_cls)["address"], ValueObject)
        assert "address" not in view_cls.model_fields

    def test_attributes_are_flattened(self, view_cls) -> None:
        assert sorted(attributes(view_cls)) == [
            "address_city",
            "address_street",
            "customer_id",
        ]

    def test_construct_and_round_trip(self, test_domain, view_cls) -> None:
        view = view_cls(
            customer_id="c-1", address=Address(street="1 Main", city="Town")
        )
        assert view.address_city == "Town"

        test_domain.repository_for(view_cls).add(view)
        loaded = test_domain.repository_for(view_cls).get("c-1")
        assert loaded.address == Address(street="1 Main", city="Town")

    def test_value_object_is_optional(self, view_cls) -> None:
        assert view_cls(customer_id="c-2").address is None
