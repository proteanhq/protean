"""Test VO functionality with Balance Value Object"""

# Protean
from tests.support.domains.banking.customer.domain.model.account import Balance, Currency


class TestBalanceVO:
    def test_init(self):
        """Test that direct initialization works"""
        balance = Balance(currency=Currency.CAD.value, amount=0.0)
        assert balance is not None
        assert balance.currency == 'CAD'
        assert balance.amount == 0.0

    def test_init_build(self):
        """Test that Balance VO can be initialized successfully"""
        balance = Balance.build(currency=Currency.CAD.value, amount=0.0)
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
