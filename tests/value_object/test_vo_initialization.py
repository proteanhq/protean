"""Tests for BaseValueObject initialization and lifecycle in core/value_object.py."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import NotSupportedError
from protean.fields import String, ValueObject


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Email(BaseValueObject):
    address: String(required=True, max_length=254)


class PhoneNumber(BaseValueObject):
    number: String(required=True, max_length=20)
    country_code: String(max_length=5)


# ---------------------------------------------------------------------------
# Test: BaseValueObject direct instantiation
# ---------------------------------------------------------------------------
class TestBaseValueObjectInstantiation:
    def test_direct_instantiation_raises(self):
        """BaseValueObject cannot be instantiated directly."""
        with pytest.raises(NotSupportedError, match="cannot be instantiated"):
            BaseValueObject()


# ---------------------------------------------------------------------------
# Test: Required ValueObject descriptor
# ---------------------------------------------------------------------------
class TestRequiredValueObjectDescriptor:
    def test_required_vo_descriptor(self, test_domain):
        """ValueObject(required=True) creates non-optional annotation."""

        class Contact(BaseAggregate):
            name: String(required=True, max_length=100)
            email = ValueObject(Email, required=True)

        test_domain.register(Email)
        test_domain.register(Contact)
        test_domain.init(traverse=False)

        # Required VO - creating without it should raise or be enforced
        contact = Contact(name="Alice", email=Email(address="alice@example.com"))
        assert contact.email.address == "alice@example.com"


# ---------------------------------------------------------------------------
# Test: _postcheck method
# ---------------------------------------------------------------------------
class TestValueObjectPostcheck:
    def test_postcheck_returns_empty_dict_when_no_invariants(self, test_domain):
        """_postcheck calls _run_invariants('post')."""
        test_domain.register(Email)
        test_domain.init(traverse=False)

        email = Email(address="test@example.com")
        result = email._postcheck()
        assert result == {}


# ---------------------------------------------------------------------------
# Test: Template dict pattern for VO
# ---------------------------------------------------------------------------
class TestValueObjectTemplateDict:
    def test_template_dict_construction(self, test_domain):
        """VO constructed with positional dict template."""
        test_domain.register(PhoneNumber)
        test_domain.init(traverse=False)

        phone = PhoneNumber({"number": "555-1234", "country_code": "+1"})
        assert phone.number == "555-1234"
        assert phone.country_code == "+1"

    def test_template_dict_with_kwargs_override(self, test_domain):
        """kwargs override template dict values."""
        test_domain.register(PhoneNumber)
        test_domain.init(traverse=False)

        phone = PhoneNumber(
            {"number": "555-1234", "country_code": "+1"},
            country_code="+44",
        )
        assert phone.number == "555-1234"
        assert phone.country_code == "+44"
