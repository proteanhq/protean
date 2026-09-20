"""
Simple Value Object - Money/Balance

This example demonstrates:
- Basic value object structure with two attributes
- Immutability concept
- No identity (two instances with same values are equal)
- Use in aggregate

Usage:
    from protean_skills.value_object.assets.value_object_simple import Balance
"""

from protean import Domain
from protean.fields import Float, String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain(__name__)


@domain.value_object
class Balance:
    """
    A balance value object representing currency and amount.

    Value objects are immutable and have no identity - two Balance
    instances with the same currency and amount are considered equal.
    """

    currency: String(max_length=3, required=True)
    amount: Float(required=True, min_value=0.0)


@domain.aggregate
class Account:
    """Account aggregate using Balance value object."""

    balance = ValueObject(Balance, required=True)
    name: String(max_length=50, required=True)


if __name__ == "__main__":
    with domain.domain_context():
        # Create a Balance value object
        bal1 = Balance(currency="USD", amount=100.0)
        print(f"Balance 1: {bal1.currency} {bal1.amount}")

        # Create another Balance with same values
        bal2 = Balance(currency="USD", amount=100.0)
        print(f"Balance 2: {bal2.currency} {bal2.amount}")

        # Two value objects with same attributes are equal
        print(f"bal1 == bal2: {bal1 == bal2}")  # True

        # Different values are not equal
        bal3 = Balance(currency="EUR", amount=100.0)
        print(f"bal1 == bal3: {bal1 == bal3}")  # False

        # Use in aggregate - assign as complete object
        account = Account(
            balance=Balance(currency="USD", amount=500.0), name="Checking"
        )
        print(
            f"\nAccount: {account.name}, Balance: {account.balance.currency} {account.balance.amount}"
        )

        # Can also initialize by attributes during creation
        account2 = Account(
            balance_currency="EUR", balance_amount=1000.0, name="Savings"
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
        account.balance = Balance(currency="USD", amount=600.0)
        print(f"\nUpdated account balance: {account.balance.amount}")
