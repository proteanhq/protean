"""Test Aggregates functionality with Customer Domain"""

# Standard Library Imports
from collections import OrderedDict
from uuid import UUID

# Protean
import pytest

from protean.core.field.embedded import ValueObjectField
from tests.old.support.domains.banking.customer.domain.model.account import Account, AccountType, Balance, Currency


class TestAccountAggregate:
    """Tests for Account Aggregate"""

    def test_account_fields(self):
        """Test Account Aggregate structure"""
        declared_fields_keys = list(OrderedDict(sorted(Account.meta_.declared_fields.items())).keys())
        assert declared_fields_keys == ['account_type', 'balance', 'id', 'name']

        attribute_keys = list(OrderedDict(sorted(Account.meta_.attributes.items())).keys())
        assert attribute_keys == ['account_type', 'balance_amount', 'balance_currency', 'id', 'name']

        assert isinstance(Account.meta_.declared_fields['balance'], ValueObjectField)

    def test_init(self):
        """Test that Account Aggregate can be initialized successfully"""
        account = Account.build(
            balance=Balance.build(currency=Currency.CAD.value, amount=500.0),
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)
        assert account is not None
        assert account.balance == Balance.build(currency=Currency.CAD.value, amount=500.0)
        assert account.account_type == AccountType.SAVINGS.value

    def test_init_with_email_vo(self):
        """Test that Account Aggregate can be initialized successfully"""
        balance = Balance.build(currency=Currency.CAD.value, amount=500.0)
        account = Account.build(
            balance=balance,
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)
        assert account is not None
        assert account.balance == Balance.build(currency=Currency.CAD.value, amount=500.0)
        assert account.balance_currency == Currency.CAD.value
        assert account.balance_amount == 500.0

        account.balance = None
        assert account.balance is None
        assert account.balance_currency is None
        assert account.balance_amount is None

        account.balance = balance
        assert account.balance == balance
        assert account.balance_currency == Currency.CAD.value

        account.balance = None
        account.balance_currency = Currency.CAD.value  # We don't accept partial updates
        assert account.balance is None
        assert account.balance_currency is None
        assert account.balance_amount is None

    def test_vo_values(self):
        """Test that values of VOs are set and retrieved properly"""
        balance = Balance.build(currency=Currency.CAD.value, amount=500.0)
        account = Account.build(
            balance=balance,
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)
        assert account.balance == balance
        assert isinstance(account.balance, Balance)
        assert account.balance.currency == Currency.CAD.value
        account_dict = account.to_dict()
        assert all(attr in account_dict
                   for attr
                   in ['account_type', 'balance_amount', 'balance_currency', 'id', 'name'])

    def test_identity(self):
        """Test that a Account Aggregate object has a unique identity"""
        account = Account.build(
            balance=Balance.build(currency=Currency.CAD.value, amount=500.0),
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)
        assert account.id is not None

        try:
            uuid_obj = UUID(str(account.id))
        except ValueError:
            pytest.fail("ID is not valid UUID")

        assert str(uuid_obj) == account.id

    def test_equivalence(self):
        """Test that two Account objects with the same ID are treated as equal"""
        account1 = Account.build(
            balance=Balance.build(currency=Currency.CAD.value, amount=500.0),
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)
        account2 = account1.clone()

        account2.name = "Premium Checking Account"
        assert account1 == account2

    def test_persistence(self, test_domain):
        """Test that the Account Aggregate can be persisted successfully"""
        account = test_domain.get_repository(Account).create(
            balance=Balance.build(currency=Currency.CAD.value, amount=500.0),
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)

        assert account is not None
        assert account.id is not None

        try:
            UUID(account.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")

    def test_retrieval(self, test_domain):
        """Test that the Account Aggregate can be retrieved successfully
        and it retains its state
        """
        account = test_domain.get_repository(Account).create(
            balance=Balance.build(currency=Currency.CAD.value, amount=500.0),
            name='Premium Savings Account',
            account_type=AccountType.SAVINGS.value)
        db_account = test_domain.get_repository(Account).get(account.id)

        assert db_account is not None
        assert db_account.balance is not None
        assert db_account.balance == Balance.build(currency=Currency.CAD.value, amount=500.0)
        assert db_account.balance_amount == 500.0
        try:
            UUID(account.id)
        except ValueError:
            pytest.fail("ID is not valid UUID")
