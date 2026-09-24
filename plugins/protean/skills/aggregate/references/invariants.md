# Invariants and Business Rules

Invariants are business rules that must always hold true for an aggregate. Protean provides decorators to enforce invariants before and after state changes.

## Overview

Invariants:
- Ensure business rules are never violated
- Are checked automatically by Protean
- Can be pre-conditions (checked before) or post-conditions (checked after)
- Raise exceptions when violated
- Help maintain aggregate consistency

## Code

The complete implementation is in [assets/aggregate_with_invariants.py](../assets/aggregate_with_invariants.py).

Key highlights:
- `@invariant.pre` decorator for pre-conditions
- `@invariant.post` decorator for post-conditions
- Custom domain exceptions for business rule violations
- Invariants checked on every state change
- Multiple invariants per aggregate

## Types of Invariants

### Post-Condition Invariants (`@invariant.post`)

Post-conditions are checked **after** a state change:

```python
@domain.aggregate
class Account:
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException(
                f"Balance cannot be below overdraft limit"
            )

    def withdraw(self, amount: float):
        self.balance -= amount
        # Post-invariant checked here
```

**Use post-conditions when:**
- You need to validate the result of a state change
- The rule depends on the new state
- You want to allow intermediate invalid states during computation

### Pre-Condition Invariants (`@invariant.pre`)

Pre-conditions are checked **before** a state change:

```python
@domain.aggregate
class Account:
    status: String(max_length=20, default="active")

    @invariant.pre
    def account_must_be_active(self):
        if self.status != "active":
            raise InvalidTransferException(
                f"Cannot perform transactions on {self.status} account"
            )

    def withdraw(self, amount: float):
        # Pre-invariant checked here first
        self.balance -= amount
```

**Use pre-conditions when:**
- You need to validate state before allowing changes
- The rule depends on current state
- You want to fail fast before any mutations

## Walkthrough

### Defining Custom Exceptions

```python
class InsufficientFundsException(Exception):
    """Raised when account balance would go below overdraft limit."""
    pass
```

Custom exceptions:
- Make error handling explicit
- Enable specific catch blocks
- Communicate business rule violations clearly

### Single Invariant Example

```python
@domain.aggregate
class Account:
    account_number: String(required=True, identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException(
                f"Balance {self.balance} cannot be below "
                f"overdraft limit -{self.overdraft_limit}"
            )

    def withdraw(self, amount: float):
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        self.balance -= amount
```

Key points:
- Invariant method name describes the rule
- Clear error messages explain what went wrong
- Pre-validation (amount > 0) vs invariant (balance limits)

### Multiple Invariants

An aggregate can have multiple invariants:

```python
@domain.aggregate
class Warehouse:
    current_stock: Float(default=0.0)
    reserved_stock: Float(default=0.0)
    max_capacity: Float(required=True)

    @invariant.post
    def stock_cannot_be_negative(self):
        if self.current_stock < 0:
            raise ValueError("Stock cannot be negative")

    @invariant.post
    def reserved_cannot_exceed_current(self):
        if self.reserved_stock > self.current_stock:
            raise ValueError(
                "Reserved stock cannot exceed current stock"
            )

    @invariant.post
    def total_cannot_exceed_capacity(self):
        if self.current_stock > self.max_capacity:
            raise ValueError("Stock exceeds capacity")
```

All invariants are checked on every state change. If any fails, the change is rejected.

### Combining Pre and Post Invariants

```python
@domain.aggregate
class Order:
    status: String(default="draft")
    line_items = HasMany("OrderLine")

    @invariant.pre
    def order_must_be_draft_to_modify(self):
        if self.status != "draft":
            raise InvalidOperationException(
                "Cannot modify non-draft order"
            )

    @invariant.post
    def placed_order_must_have_items(self):
        if self.status == "placed" and not self.line_items:
            raise InvalidOperationException(
                "Cannot place order without items"
            )

    def add_item(self, item: OrderLine):
        # Pre-check: must be draft
        self.add_line_items(item)
        # Post-check: runs, but won't fail (still draft)

    def place_order(self):
        # Pre-check: must be draft
        self.status = "placed"
        # Post-check: must have items
```

## Field-Level Validation vs Invariants

There's an important distinction:

### Field-Level Validation

```python
class Account:
    balance: Float(required=True)  # Must exist
    account_number: String(required=True, max_length=50)  # Format constraints
```

Field validation checks:
- Data type correctness
- Required/optional
- String length, numeric ranges
- Choice constraints

### Invariants (Business Rules)

```python
@invariant.post
def balance_must_be_above_overdraft_limit(self):
    if self.balance < -self.overdraft_limit:
        raise InsufficientFundsException(...)
```

Invariants check:
- Relationships between fields
- Business domain rules
- State-dependent constraints
- Cross-aggregate rules (via domain services)

**Rule of thumb:**
- Use field validation for single-field constraints
- Use invariants for business rules involving multiple fields or complex logic

## When Invariants Are Checked

Protean checks invariants:

1. **After initialization**: When creating a new aggregate instance
2. **After any mutation**: When calling methods that change state
3. **Before persistence**: When saving to repository

```python
# Checked after __init__
account = Account(balance=-500.0, overdraft_limit=100.0)
# Raises InsufficientFundsException

# Checked after state change
account = Account(balance=1000.0, overdraft_limit=100.0)
account.withdraw(1200.0)
# Raises InsufficientFundsException

# Checked before save
account = Account(balance=500.0, overdraft_limit=100.0)
account.balance = -200.0  # Direct mutation
domain.repository_for(Account).add(account)
# Raises InsufficientFundsException
```

## Best Practices

1. **Name invariants descriptively** - Method name should explain the rule
2. **Use domain exceptions** - Create custom exception classes for business rules
3. **Provide clear error messages** - Include context about what failed and why
4. **Keep invariants simple** - Each method should check one rule
5. **Use pre-conditions for state validation** - Check if operations are allowed
6. **Use post-conditions for result validation** - Check if changes are valid
7. **Validate early** - Use field validation for simple constraints, invariants for business rules

## Common Patterns

### Invariant with Multiple Conditions

```python
@invariant.post
def order_state_consistency(self):
    if self.status == "placed":
        if not self.line_items:
            raise ValueError("Placed order must have items")
        if not self.payment_info:
            raise ValueError("Placed order must have payment")
    if self.status == "shipped":
        if not self.shipping_info:
            raise ValueError("Shipped order must have shipping info")
```

### Invariant with Helper Method

```python
@domain.aggregate
class ShoppingCart:
    items = HasMany("CartItem")
    max_items: Integer(default=50)

    def _total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @invariant.post
    def cart_cannot_exceed_max_items(self):
        if self._total_quantity() > self.max_items:
            raise ValueError(
                f"Cart cannot exceed {self.max_items} items"
            )
```

### Soft Invariants (Warnings)

Sometimes you want to log violations without failing:

```python
import logging

@invariant.post
def warn_on_low_stock(self):
    if self.current_stock < self.reorder_level:
        logging.warning(
            f"Stock for {self.name} is below reorder level"
        )
    # Don't raise - this is a warning, not a hard failure
```

## Testing Invariants

```python
def test_account_overdraft_invariant():
    account = Account(balance=1000.0, overdraft_limit=100.0)

    # Should succeed
    account.withdraw(1000.0)
    assert account.balance == 0.0

    # Should fail
    with pytest.raises(InsufficientFundsException):
        account.withdraw(200.0)
```

## Related

- [Anti-patterns](./anti-patterns.md) - Common invariant mistakes
- [domain-service](../../domain-service/SKILL.md) - Cross-aggregate invariants
