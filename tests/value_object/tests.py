# Protean
import pytest

from protean.core.exceptions import InvalidOperationError, ValidationError

# Local/Relative Imports
from .elements import Balance, Currency, Email, MyOrgEmail


class TestEquivalence:
    def test_two_value_objects_with_equal_values_are_considered_equal(self):
        email1 = Email.from_address('john.doe@gmail.com')
        email2 = Email.from_address('john.doe@gmail.com')

        assert email1 == email2

    def test_that_two_value_objects_with_different_values_are_different(self):
        email3 = Email.from_address('john.doe@gmail.com')
        email4 = Email.from_address('jane.doe@gmail.com')

        assert email3 != email4

    def test_that_two_value_objects_of_inherited_types_are_different_even_with_same_values(self):
        email = Email.from_address('john.doe@gmail.com')
        my_org_email = MyOrgEmail.from_address('john.doe@gmail.com')

        assert email != my_org_email

    def test_generated_value_object_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_value = hash(frozenset({'address': 'john.doe@gmail.com'}.items()))

        email = Email.from_address('john.doe@gmail.com')
        assert hash(email) == hashed_value

    def test_that_two_value_objects_that_are_equal_have_equal_hash(self):
        email1 = Email.from_address('john.doe@gmail.com')
        email2 = Email.from_address('john.doe@gmail.com')

        assert email1 == email2
        assert hash(email1) == hash(email2)


class TestEmailVOProperties:
    def test_output_to_dict(self):
        email = Email.from_address('john.doe@gmail.com')
        assert email.to_dict() == {'address': 'john.doe@gmail.com'}

    def test_repr_output_of_value_object(self):
        email = Email.from_address('john.doe@gmail.com')
        assert repr(email) == "<Email: Email object ({'address': 'john.doe@gmail.com'})>"

    def test_str_output_of_value_object(self):
        email = Email.from_address('john.doe@gmail.com')
        assert str(email) == "Email object ({'address': 'john.doe@gmail.com'})"

    @pytest.mark.xfail
    def test_that_value_objects_are_immutable(self):
        email = Email.from_address(address='john.doe@gmail.com')
        with pytest.raises(InvalidOperationError):
            email.local_part = 'jane.doe'


class TestEmailVOStructure:
    def test_email_vo_has_address_field(self):
        assert len(Email.meta_.declared_fields) == 1
        assert 'address' in Email.meta_.declared_fields


class TestBalanceVOStructure:
    def test_balance_vo_has_currency_and_amount_fields(self):
        assert len(Balance.meta_.declared_fields) == 2
        assert 'currency' in Balance.meta_.declared_fields
        assert 'amount' in Balance.meta_.declared_fields

    def test_output_to_dict(self):
        balance = Balance.build(currency=Currency.USD.value, amount=0.0)
        assert balance.to_dict() == {'currency': 'USD', 'amount': 0.0}

    def test_repr_output_of_value_object(self):
        balance = Balance.build(currency=Currency.USD.value, amount=0.0)
        assert repr(balance) == "<Balance: Balance object ({'currency': 'USD', 'amount': 0.0})>"

    def test_str_output_of_value_object(self):
        balance = Balance.build(currency=Currency.USD.value, amount=0.0)
        assert str(balance) == "Balance object ({'currency': 'USD', 'amount': 0.0})"


class TestBalanceVOBehavior:
    def test_init(self):
        """Test that direct initialization works"""
        balance = Balance(currency=Currency.CAD.value, amount=0.0)
        assert balance is not None
        assert balance.currency == 'CAD'
        assert balance.amount == 0.0

    def test_equivalence(self):
        """Test that two Balance VOs are equal if their values are equal"""
        balance1 = Balance.build(currency=Currency.USD.value, amount=0.0)
        balance2 = Balance.build(currency=Currency.USD.value, amount=0.0)

        assert balance1 == balance2

        balance3 = Balance.build(currency=Currency.INR.value, amount=0.0)

        assert balance3 != balance1

    def test_that_only_valid_currencies_can_be_assigned_to_balance_object(self):
        with pytest.raises(ValidationError):
            Balance.build(currency='FOO', amount=0.0)

    def test_that_only_valid_float_values_can_be_assigned_to_balance_object(self):
        with pytest.raises(ValidationError):
            Balance.build(currency='FOO', amount='abc')

    def test_that_a_negative_balance_less_than_one_trillion_is_invalid(self):
        with pytest.raises(ValidationError):
            Balance.build(currency='FOO', amount=-100000000000000.0)

    def test_that_new_balance_object_is_generated_with_replace_method(self):
        balance1 = Balance.build(currency=Currency.CAD.value, amount=0.0)
        balance2 = balance1.replace()

        assert balance2 is not balance1
        assert balance2 == balance1

        balance3 = balance1.replace(amount=150.0)
        assert balance1.amount == 0.0
        assert balance3.amount == 150.0

        balance4 = balance1.replace(currency='INR')
        assert balance1.currency == Currency.CAD.value
        assert balance4.currency == Currency.INR.value


class TestEmailVOBehavior:
    def test_validity(self):
        assert Email.validate('john.doe@gmail.com')
        assert not Email.validate('john.doe')
        assert not Email.validate('1234567890@gmail.com' * 26)

        with pytest.raises(ValueError):
            Email.from_address('john.doe')

    def test_init_from_constructor(self):
        email = Email(local_part='john.doe', domain_part='gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'

    def test_init_from_parts(self):
        email = Email.from_parts('john.doe', 'gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'

    def test_init_build(self):
        email = Email.from_address('john.doe@gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'
