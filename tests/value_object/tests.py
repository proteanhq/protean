import pytest

from protean.exceptions import InvalidOperationError, ValidationError

from .elements import (
    Account,
    Balance,
    Currency,
    Email,
    MyOrgEmail,
    PolymorphicConnection,
    PolymorphicOwner,
    User,
)


class TestEquivalence:
    def test_two_value_objects_with_equal_values_are_considered_equal(self):
        email1 = Email.from_address("john.doe@gmail.com")
        email2 = Email.from_address("john.doe@gmail.com")

        assert email1 == email2

    def test_that_two_value_objects_with_different_values_are_different(self):
        email3 = Email.from_address("john.doe@gmail.com")
        email4 = Email.from_address("jane.doe@gmail.com")

        assert email3 != email4

    def test_that_two_value_objects_of_inherited_types_are_different_even_with_same_values(
        self,
    ):
        email = Email.from_address("john.doe@gmail.com")
        my_org_email = MyOrgEmail.from_address("john.doe@gmail.com")

        assert email != my_org_email

    def test_generated_value_object_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_value = hash(frozenset({"address": "john.doe@gmail.com"}.items()))

        email = Email.from_address("john.doe@gmail.com")
        assert hash(email) == hashed_value

    def test_that_two_value_objects_that_are_equal_have_equal_hash(self):
        email1 = Email.from_address("john.doe@gmail.com")
        email2 = Email.from_address("john.doe@gmail.com")

        assert email1 == email2
        assert hash(email1) == hash(email2)


class TestEmailVOProperties:
    def test_output_to_dict(self):
        email = Email.from_address("john.doe@gmail.com")
        assert email.to_dict() == {"address": "john.doe@gmail.com"}

    def test_repr_output_of_value_object(self):
        email = Email.from_address("john.doe@gmail.com")
        assert (
            repr(email) == "<Email: Email object ({'address': 'john.doe@gmail.com'})>"
        )

    def test_str_output_of_value_object(self):
        email = Email.from_address("john.doe@gmail.com")
        assert str(email) == "Email object ({'address': 'john.doe@gmail.com'})"

    @pytest.mark.xfail
    def test_that_value_objects_are_immutable(self):
        email = Email.from_address(address="john.doe@gmail.com")
        with pytest.raises(InvalidOperationError):
            email.address = "jane.doe@gmail.com"


class TestEmailVOStructure:
    def test_email_vo_has_address_field(self):
        assert len(Email.meta_.declared_fields) == 1
        assert "address" in Email.meta_.declared_fields


class TestBalanceVOStructure:
    def test_balance_vo_has_currency_and_amount_fields(self):
        assert len(Balance.meta_.declared_fields) == 2
        assert "currency" in Balance.meta_.declared_fields
        assert "amount" in Balance.meta_.declared_fields

    def test_output_to_dict(self):
        balance = Balance.build(currency=Currency.USD.value, amount=0.0)
        assert balance.to_dict() == {"currency": "USD", "amount": 0.0}

    def test_repr_output_of_value_object(self):
        balance = Balance.build(currency=Currency.USD.value, amount=0.0)
        assert (
            repr(balance)
            == "<Balance: Balance object ({'currency': 'USD', 'amount': 0.0})>"
        )

    def test_str_output_of_value_object(self):
        balance = Balance.build(currency=Currency.USD.value, amount=0.0)
        assert str(balance) == "Balance object ({'currency': 'USD', 'amount': 0.0})"


class TestBalanceVOBehavior:
    def test_init(self):
        """Test that direct initialization works"""
        balance = Balance(currency=Currency.CAD.value, amount=0.0)
        assert balance is not None
        assert balance.currency == "CAD"
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
            Balance.build(currency="FOO", amount=0.0)

    def test_that_only_valid_float_values_can_be_assigned_to_balance_object(self):
        with pytest.raises(ValidationError):
            Balance.build(currency="FOO", amount="abc")

    def test_that_a_negative_balance_less_than_one_trillion_is_invalid(self):
        with pytest.raises(ValidationError):
            Balance.build(currency="FOO", amount=-100000000000000.0)

    def test_that_new_balance_object_is_generated_with_replace_method(self):
        balance1 = Balance.build(currency=Currency.CAD.value, amount=0.0)
        balance2 = balance1.replace()

        assert balance2 is not balance1
        assert balance2 == balance1

        balance3 = balance1.replace(amount=150.0)
        assert balance1.amount == 0.0
        assert balance3.amount == 150.0

        balance4 = balance1.replace(currency="INR")
        assert balance1.currency == Currency.CAD.value
        assert balance4.currency == Currency.INR.value


class TestEmailVOBehavior:
    def test_validity(self):
        assert Email.validate("john.doe@gmail.com")
        assert not Email.validate("john.doe")
        assert not Email.validate("1234567890@gmail.com" * 26)

        with pytest.raises(ValueError):
            Email.from_address("john.doe")

    def test_init_from_constructor(self):
        email = Email(address="john.doe@gmail.com")
        assert email is not None
        assert email.address == "john.doe@gmail.com"

    def test_init_build(self):
        email = Email.from_address("john.doe@gmail.com")
        assert email is not None
        assert email.address == "john.doe@gmail.com"


class TestEmailVOEmbedding:
    def test_that_user_has_all_the_required_fields(self):
        assert all(
            field_name in User.meta_.declared_fields for field_name in ["email", "name"]
        )

    def test_that_user_can_be_initialized_successfully(self):
        user = User(email=Email.from_address("john.doe@gmail.com"))
        assert user is not None
        assert user.id is not None
        assert user.email == Email.from_address(address="john.doe@gmail.com")
        assert user.email_address == "john.doe@gmail.com"

    def test_that_user_can_be_initialized_successfully_with_embedded_fields(self):
        user = User(email_address="john.doe@gmail.com", name="John Doe")
        assert user is not None
        assert user.id is not None
        assert user.email == Email.from_address("john.doe@gmail.com")
        assert user.email_address == "john.doe@gmail.com"

    def test_that_mandatory_fields_are_validated(self):
        with pytest.raises(ValidationError) as multi_exceptions:
            User()

        assert "email_address" in multi_exceptions.value.messages
        assert multi_exceptions.value.messages["email_address"] == ["is required"]

        with pytest.raises(ValidationError) as email_exception:
            User(name="John Doe")

        assert "email_address" in email_exception.value.messages
        assert email_exception.value.messages["email_address"] == ["is required"]


class TestBalanceVOEmbedding:
    def test_that_account_has_all_the_required_fields(self):
        assert all(
            field_name in Account.meta_.declared_fields
            for field_name in ["balance", "kind"]
        )

    def test_that_account_can_be_initialized_successfully(self):
        account = Account(
            balance=Balance.build(currency="USD", amount=150.0), kind="PRIMARY"
        )
        assert account is not None
        assert account.id is not None
        assert account.balance == Balance.build(currency="USD", amount=150.0)
        assert account.balance_currency == "USD"
        assert account.balance_amount == 150.0

    def test_that_account_can_be_initialized_successfully_with_embedded_fields(self):
        account = Account(balance_currency="USD", balance_amount=150.0, kind="PRIMARY")
        assert account is not None
        assert account.id is not None
        assert account.balance == Balance.build(currency="USD", amount=150.0)
        assert account.balance_currency == "USD"
        assert account.balance_amount == 150.0

    def test_that_mandatory_fields_are_validated(self):
        with pytest.raises(ValidationError) as multi_exceptions:
            Account()

        assert "balance" in multi_exceptions.value.messages
        assert multi_exceptions.value.messages["balance"] == ["is required"]
        assert "kind" in multi_exceptions.value.messages
        assert multi_exceptions.value.messages["kind"] == ["is required"]

        with pytest.raises(ValidationError) as email_exception:
            Account(kind="PRIMARY")

        assert "balance" in email_exception.value.messages
        assert email_exception.value.messages["balance"] == ["is required"]


class TestNamedEmbedding:
    def test_that_explicit_names_are_used(self):
        assert len(PolymorphicConnection.meta_.declared_fields) == 2
        assert "connected_id" in PolymorphicConnection.meta_.declared_fields
        assert "connected_type" in PolymorphicConnection.meta_.declared_fields

    def test_that_explicit_names_are_preserved_in_aggregate(self):
        assert len(PolymorphicOwner.meta_.declared_fields) == 2
        assert "id" in PolymorphicOwner.meta_.declared_fields
        assert "connector" in PolymorphicOwner.meta_.declared_fields

        owner = PolymorphicOwner()
        assert owner.meta_.attributes is not None
        assert "connected_id" in owner.meta_.attributes
        assert "connected_type" in owner.meta_.attributes
