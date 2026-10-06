"""
Simple Value Object - Money/Balance

This example demonstrates:
- Basic value object structure with two attributes
- Immutability concept
- No identity (two instances with same values are equal)
- Use in aggregate

Usage:
    python value_object_simple.py
"""

from decimal import Decimal as D

from protean import Domain
from protean.fields import Decimal, String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain()


@domain.value_object
class Balance:
    """
    A balance value object representing currency and amount.

    Value objects are immutable and have no identity - two Balance
    instances with the same currency and amount are considered equal.
    """

    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True, min_value=0)


@domain.aggregate
class Account:
    """Account aggregate using Balance value object."""

    balance = ValueObject(Balance, required=True)
    name: String(max_length=50, required=True)


if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a Balance value object
        bal1 = Balance(currency="USD", amount=D("100.00"))
        print(f"Balance 1: {bal1.currency} {bal1.amount}")

        # Create another Balance with same values
        bal2 = Balance(currency="USD", amount=D("100.00"))
        print(f"Balance 2: {bal2.currency} {bal2.amount}")

        # Two value objects with same attributes are equal
        print(f"bal1 == bal2: {bal1 == bal2}")  # True

        # Different values are not equal
        bal3 = Balance(currency="EUR", amount=D("100.00"))
        print(f"bal1 == bal3: {bal1 == bal3}")  # False

        # Use in aggregate - assign as complete object
        account = Account(
            balance=Balance(currency="USD", amount=D("500.00")), name="Checking"
        )
        print(
            f"\nAccount: {account.name}, Balance: {account.balance.currency} {account.balance.amount}"
        )

        # Can also initialize by attributes during creation
        account2 = Account(
            balance_currency="EUR", balance_amount=D("1000.00"), name="Savings"
        )
        print(
            f"Account 2: {account2.name}, Balance: {account2.balance.currency} {account2.balance.amount}"
        )

        # Value objects are immutable - cannot change once created
        try:
            bal1.currency = "EUR"  # Will raise IncorrectUsageError
        except Exception as e:
            print(f"\nImmutability enforced: {e}")

        # To "change" a value object, replace it entirely
        account.balance = Balance(currency="USD", amount=D("600.00"))
        print(f"\nUpdated account balance: {account.balance.amount}")
