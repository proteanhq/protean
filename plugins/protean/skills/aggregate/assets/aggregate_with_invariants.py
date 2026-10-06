"""
Aggregate with invariant validation (business rules).

This example demonstrates:
- Invariant decorators (@invariant.pre and @invariant.post)
- Business rule enforcement at aggregate level
- Field-level validation vs invariant validation
- Raising the dict form of ValidationError on invariant violations
- State-changing methods with invariants

Usage:
    account = Account(account_number="ACC-001", balance="1000.00", overdraft_limit="100.00")
    account.withdraw("500.00")  # OK
    account.withdraw("700.00")  # Raises ValidationError
"""

from decimal import Decimal as D

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Decimal, Float, String

# Domain setup
domain = Domain()


# Custom domain exception, raised by an ordinary method. An invariant raises
# ValidationError instead, so the framework collects its failure.
class InvalidTransferException(Exception):
    """Raised when transfer violates business rules."""


@domain.aggregate
class Account:
    """Bank account with balance invariants."""

    account_number: String(required=True, max_length=50, identifier=True)
    # Can be negative within overdraft_limit
    balance: Decimal(precision=19, scale=4, default=0)
    # Field-level validation
    overdraft_limit: Decimal(precision=19, scale=4, default=0, min_value=0)
    status: String(max_length=20, default="active")

    # Post-condition invariant: checked at the end of __init__ and after
    # every field assignment
    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        """Balance must not fall below the negative overdraft limit."""
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {
                    "_entity": [
                        f"Balance {self.balance} cannot be below "
                        f"overdraft limit -{self.overdraft_limit}"
                    ]
                }
            )

    # Pre-condition invariant: checked before every field assignment
    @invariant.pre
    def account_must_be_active(self):
        """Account must be active for transactions."""
        if self.status != "active":
            raise ValidationError(
                {"status": [f"Cannot perform transactions on {self.status} account"]}
            )

    def deposit(self, amount):
        """Deposit money into the account."""
        amount = D(str(amount))  # Accept int, float, str or Decimal
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.balance += amount

    def withdraw(self, amount):
        """
        Withdraw money from the account.

        The balance_must_be_above_overdraft_limit invariant
        is checked on the assignment to self.balance.
        """
        amount = D(str(amount))  # Accept int, float, str or Decimal
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        self.balance -= amount

    def close_account(self):
        """Close the account (requires zero balance)."""
        if self.balance != 0:
            raise InvalidTransferException("Cannot close account with non-zero balance")
        self.status = "closed"


@domain.aggregate
class Warehouse:
    """Warehouse with inventory invariants."""

    name: String(required=True, max_length=100)
    # Field-level validation for non-negative stock values
    current_stock: Float(default=0.0, min_value=0.0)
    reserved_stock: Float(default=0.0, min_value=0.0)
    max_capacity: Float(required=True, min_value=0.0)

    # Note: stock_cannot_be_negative is now enforced by field min_value=0.0
    # Use invariants for cross-field business rules, not simple data constraints

    @invariant.post
    def reserved_stock_cannot_exceed_current(self):
        """Reserved stock cannot exceed available stock."""
        if self.reserved_stock > self.current_stock:
            raise ValidationError(
                {
                    "_entity": [
                        f"Reserved stock {self.reserved_stock} exceeds "
                        f"current stock {self.current_stock}"
                    ]
                }
            )

    @invariant.post
    def total_stock_cannot_exceed_capacity(self):
        """Total stock cannot exceed warehouse capacity."""
        if self.current_stock > self.max_capacity:
            raise ValidationError(
                {
                    "_entity": [
                        f"Stock {self.current_stock} exceeds capacity {self.max_capacity}"
                    ]
                }
            )

    def receive_stock(self, quantity: float):
        """Receive stock into warehouse."""
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        self.current_stock += quantity
        # Invariant will check if capacity is exceeded

    def reserve_stock(self, quantity: float):
        """Reserve stock for an order."""
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        available = self.current_stock - self.reserved_stock
        if quantity > available:
            raise ValueError(f"Cannot reserve {quantity}, only {available} available")
        self.reserved_stock += quantity
        # Invariant will check if reserved exceeds current

    def ship_stock(self, quantity: float):
        """Ship reserved stock."""
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if quantity > self.reserved_stock:
            raise ValueError(
                f"Cannot ship {quantity}, only {self.reserved_stock} reserved"
            )
        self.current_stock -= quantity
        self.reserved_stock -= quantity
        # Invariants will check all constraints


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        print("=== Account Example ===")

        # Create account
        account = Account(
            account_number="ACC-12345", balance="1000.00", overdraft_limit="200.00"
        )

        print(f"Initial balance: ${account.balance:.2f}")

        # Successful withdrawal
        account.withdraw("500.00")
        print(f"After withdrawal of $500: ${account.balance:.2f}")

        # Another withdrawal within overdraft limit
        account.withdraw("600.00")
        print(f"After withdrawal of $600: ${account.balance:.2f}")

        # Try to withdraw beyond overdraft limit
        balance_before_failed_withdrawal = account.balance
        try:
            account.withdraw("200.00")
        except ValidationError as e:
            print(f"Failed: {dict(e.messages)}")
            # The account now holds the invalid balance. Discard it, don't persist it.

        print(
            f"Balance before failed withdrawal: ${balance_before_failed_withdrawal:.2f}"
        )
        print(
            f"Balance after failed withdrawal: ${account.balance:.2f} (invalid state!)"
        )

        print("\n=== Warehouse Example ===")

        # Create warehouse
        warehouse = Warehouse(name="Main Warehouse", max_capacity=10000.0)

        print(f"Initial stock: {warehouse.current_stock}")

        # Receive stock
        warehouse.receive_stock(5000.0)
        print(f"After receiving 5000: {warehouse.current_stock}")

        # Reserve some stock
        warehouse.reserve_stock(2000.0)
        print(f"Reserved: {warehouse.reserved_stock}")

        # Ship reserved stock
        warehouse.ship_stock(2000.0)
        print(
            f"After shipping: current={warehouse.current_stock}, reserved={warehouse.reserved_stock}"
        )

        # Try to exceed capacity
        try:
            warehouse.receive_stock(8000.0)
        except ValidationError as e:
            print(f"Failed: {dict(e.messages)}")
