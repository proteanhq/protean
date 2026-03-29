"""Tests for BaseValueObject.replace() method."""

import pytest

from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import String, ValueObject

from .elements import Balance, Currency


class Address(BaseValueObject):
    street: String(max_length=50)
    city: String(max_length=25)
    state: String(max_length=25)


class Contact(BaseValueObject):
    email: String(max_length=255)
    phone_number: String(max_length=255)
    address = ValueObject(Address)


class OptionalFields(BaseValueObject):
    name: String(max_length=50, required=True)
    nickname: String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Balance)
    test_domain.register(Contact)
    test_domain.register(Address)
    test_domain.register(OptionalFields)
    test_domain.init(traverse=False)


class TestReplaceBasic:
    def test_replace_with_no_args_returns_equal_copy(self):
        balance = Balance(currency="USD", amount=100.0)
        copy = balance.replace()

        assert copy is not balance
        assert copy == balance

    def test_replace_single_field(self):
        balance = Balance(currency="USD", amount=100.0)
        updated = balance.replace(amount=200.0)

        assert updated.amount == 200.0
        assert updated.currency == "USD"

    def test_replace_multiple_fields(self):
        balance = Balance(currency="USD", amount=100.0)
        updated = balance.replace(currency="INR", amount=500.0)

        assert updated.currency == "INR"
        assert updated.amount == 500.0

    def test_original_is_not_modified(self):
        balance = Balance(currency="USD", amount=100.0)
        balance.replace(amount=999.0)

        assert balance.amount == 100.0
        assert balance.currency == "USD"

    def test_replace_with_enum_value(self):
        balance = Balance(currency=Currency.CAD.value, amount=0.0)
        updated = balance.replace(currency=Currency.INR.value)

        assert updated.currency == Currency.INR.value
        assert updated.amount == 0.0


class TestReplaceNoneHandling:
    def test_replace_with_explicit_none_sets_field_to_none(self):
        vo = OptionalFields(name="Alice", nickname="Ali")
        updated = vo.replace(nickname=None)

        assert updated.name == "Alice"
        assert updated.nickname is None

    def test_replace_preserves_none_when_not_specified(self):
        vo = OptionalFields(name="Alice")
        assert vo.nickname is None

        updated = vo.replace(name="Bob")
        assert updated.name == "Bob"
        assert updated.nickname is None


class TestReplaceNestedVO:
    def test_replace_nested_value_object(self):
        addr = Address(street="123 Main St", city="Springfield", state="IL")
        contact = Contact(
            email="test@example.com",
            phone_number="555-1234",
            address=addr,
        )

        new_addr = Address(street="456 Oak Ave", city="Portland", state="OR")
        updated = contact.replace(address=new_addr)

        assert updated.address == new_addr
        assert updated.email == "test@example.com"
        assert contact.address == addr  # original unchanged

    def test_replace_preserves_nested_vo_when_not_specified(self):
        addr = Address(street="123 Main St", city="Springfield", state="IL")
        contact = Contact(
            email="test@example.com",
            phone_number="555-1234",
            address=addr,
        )

        updated = contact.replace(email="new@example.com")
        assert updated.address == addr
        assert updated.email == "new@example.com"


class TestReplaceValidation:
    def test_replace_rejects_unknown_fields(self):
        balance = Balance(currency="USD", amount=100.0)

        with pytest.raises(IncorrectUsageError, match="Unknown field.*nonexistent"):
            balance.replace(nonexistent=42)

    def test_replace_rejects_multiple_unknown_fields(self):
        balance = Balance(currency="USD", amount=100.0)

        with pytest.raises(IncorrectUsageError, match="Unknown field"):
            balance.replace(foo=1, bar=2)

    def test_replace_runs_invariants_on_new_instance(self):
        balance = Balance(currency="USD", amount=100.0)

        with pytest.raises(ValidationError):
            balance.replace(amount=-100000000000000.0)

    def test_replace_runs_pydantic_validation(self):
        balance = Balance(currency="USD", amount=100.0)

        with pytest.raises(ValidationError):
            balance.replace(amount="not_a_number")
