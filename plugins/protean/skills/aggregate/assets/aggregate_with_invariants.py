"""
Aggregate with invariant validation (business rules).

This example demonstrates:
- Invariant decorators (@invariant.pre and @invariant.post)
- Business rule enforcement at aggregate level
- Field-level validation vs invariant validation
- Raising domain exceptions on invariant violations
- State-changing methods with invariants

Usage:
    account = Account(account_number="ACC-001", balance=1000.0, overdraft_limit=100.0)
    account.withdraw(500.0)  # OK
    account.withdraw(700.0)  # Raises InsufficientFundsException
"""

from protean import Domain, invariant
from protean.fields import Float, String

# Domain setup
domain = Domain()


# Custom domain exception
class InsufficientFundsException(Exception):
    """Raised when account balance would go below overdraft limit."""


class InvalidTransferException(Exception):
    """Raised when transfer violates business rules."""


@domain.aggregate
class Account:
    """Bank account with balance invariants."""

    account_number: String(required=True, max_length=50, identifier=True)
    balance: Float(default=0.0)  # Can be negative within overdraft_limit
    overdraft_limit: Float(default=0.0, min_value=0.0)  # Field-level validation
    status: String(max_length=20, default="active")

    # Post-condition invariant: checked after any state change
    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        """Balance must not fall below the negative overdraft limit."""
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException(
                f"Balance {self.balance} cannot be below overdraft limit -{self.overdraft_limit}"
            )

    # Pre-condition invariant: checked before state changes
    @invariant.pre
    def account_must_be_active(self):
        """Account must be active for transactions."""
        if self.status != "active":
            raise InvalidTransferException(
                f"Cannot perform transactions on {self.status} account"
            )

    def deposit(self, amount: float):
        """Deposit money into the account."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.balance += amount

    def withdraw(self, amount: float):
        """
        Withdraw money from the account.

        The balance_must_be_above_overdraft_limit invariant
        will be checked after this method executes.
        """
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
            raise ValueError(
                f"Reserved stock {self.reserved_stock} exceeds current stock {self.current_stock}"
            )

    @invariant.post
    def total_stock_cannot_exceed_capacity(self):
        """Total stock cannot exceed warehouse capacity."""
        if self.current_stock > self.max_capacity:
            raise ValueError(
                f"Stock {self.current_stock} exceeds capacity {self.max_capacity}"
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
            account_number="ACC-12345", balance=1000.0, overdraft_limit=200.0
        )

        print(f"Initial balance: ${account.balance:.2f}")

        # Successful withdrawal
        account.withdraw(500.0)
        print(f"After withdrawal of $500: ${account.balance:.2f}")

        # Another withdrawal within overdraft limit
        account.withdraw(600.0)
        print(f"After withdrawal of $600: ${account.balance:.2f}")

        # Try to withdraw beyond overdraft limit
        balance_before_failed_withdrawal = account.balance
        try:
            account.withdraw(200.0)
        except InsufficientFundsException as e:
            print(f"Failed: {e}")
            # Note: Account is now in invalid state, don't save it!

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
            warehouse.receive_stock(6000.0)
        except ValueError as e:
            print(f"Failed: {e}")
