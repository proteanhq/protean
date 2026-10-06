# Invariants and Business Rules

Invariants are business rules that must always hold true for an aggregate. Protean provides decorators to enforce invariants before and after state changes.

## Overview

Invariants:
- Ensure business rules are never violated
- Are checked automatically by Protean
- Can be pre-conditions (checked before a change) or post-conditions (checked after it)
- Raise `ValidationError` in its dict form when violated
- Help maintain aggregate consistency

## Code

The complete implementation is in [assets/aggregate_with_invariants.py](../assets/aggregate_with_invariants.py).

Key highlights:
- `@invariant.pre` decorator for pre-conditions
- `@invariant.post` decorator for post-conditions
- `ValidationError({"field": ["message"]})` for every rule violation
- Invariants checked at the end of `__init__` and on every field assignment
- Multiple invariants per aggregate

## Types of Invariants

### Post-Condition Invariants (`@invariant.post`)

Post-conditions are checked **after** a state change:

```python
from decimal import Decimal as D

from protean.exceptions import ValidationError


@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0)
    overdraft_limit: Decimal(precision=19, scale=4, default=0)

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {"_entity": ["Balance cannot be below overdraft limit"]}
            )

    def withdraw(self, amount):
        self.balance -= amount
        # Post-invariant checked here, on the assignment
```

**Use post-conditions when:**
- You need to validate the result of a state change
- The rule depends on the new state
- Several fields change together: wrap the changes in `atomic_change` so the check runs once, at the end

### Pre-Condition Invariants (`@invariant.pre`)

Pre-conditions are checked **before** a state change. A failing pre-condition
rejects the change, so the field keeps its old value:

```python
@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0)
    status: String(max_length=20, default="active")

    @invariant.pre
    def account_must_be_active(self):
        if self.status != "active":
            raise ValidationError(
                {"status": [f"Cannot perform transactions on {self.status} account"]}
            )

    def withdraw(self, amount):
        # Pre-invariant checked first, on the assignment
        self.balance -= amount
```

**Use pre-conditions when:**
- You need to validate state before allowing changes
- The rule depends on current state
- You want to fail fast before any mutations

## Walkthrough

### Raising the Error

An invariant signals a broken rule by raising `ValidationError` with a dict that
maps a key to a list of messages:

```python
# fragment
raise ValidationError({"_entity": ["Balance cannot be below overdraft limit"]})
```

- A rule about one field uses that field's name as the key, even when another
  field decides whether the rule applies ("a placed order must have line items"
  uses `line_items`). A rule that compares fields, such as a balance against an
  overdraft limit, uses `_entity`, the key the framework itself uses.
- Protean catches only `ValidationError` from an invariant. It collects the
  messages from every failing invariant and raises one `ValidationError`. On an
  aggregate or entity, `err.codes` holds `INVARIANT_PRE_FAILED` or
  `INVARIANT_POST_FAILED`. On a value object it holds
  `VALUE_OBJECT_INVARIANT_FAILED`. A `code=` argument on the decorator replaces
  the default code.
- Any other exception (`ValueError`, a custom exception class) gets no code.
  Raised while the object is being built, it comes back as
  `ValidationError({"_entity": [...]})`. Raised on a later change, it escapes
  as it is. A plain-string `ValidationError("...")` fails with a `TypeError`,
  because the framework reads the messages as a dict.

### Single Invariant Example

```python
@domain.aggregate
class Account:
    account_number: String(required=True, identifier=True)
    balance: Decimal(precision=19, scale=4, default=0)
    overdraft_limit: Decimal(precision=19, scale=4, default=0)

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {
                    "_entity": [
                        f"Balance {self.balance} cannot be below "
                        f"overdraft limit -{self.overdraft_limit}"
                    ]
                }
            )

    def withdraw(self, amount):
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
            raise ValidationError({"current_stock": ["Stock cannot be negative"]})

    @invariant.post
    def reserved_cannot_exceed_current(self):
        if self.reserved_stock > self.current_stock:
            raise ValidationError(
                {"_entity": ["Reserved stock cannot exceed current stock"]}
            )

    @invariant.post
    def total_cannot_exceed_capacity(self):
        if self.current_stock > self.max_capacity:
            raise ValidationError({"_entity": ["Stock exceeds capacity"]})
```

All post-invariants are checked on every field assignment. If any fails, the
assignment raises `ValidationError`. The change is not undone: the object keeps
the invalid value, so discard it instead of persisting it.

### Combining Pre and Post Invariants

```python
@domain.entity(part_of="Order")
class OrderLine:
    sku: String(required=True)
    quantity: Integer(default=1, min_value=1)


@domain.aggregate
class Order:
    status: String(default="draft")
    line_items = HasMany("OrderLine")

    @invariant.pre
    def order_must_be_draft_to_modify(self):
        if self.status != "draft":
            raise ValidationError({"status": ["Cannot modify non-draft order"]})

    @invariant.post
    def placed_order_must_have_items(self):
        if self.status == "placed" and not self.line_items:
            raise ValidationError({"line_items": ["Cannot place order without items"]})

    def add_item(self, item: OrderLine):
        # Adding a child checks the root's invariants too
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
# fragment
class Account:
    balance: Decimal(precision=19, scale=4, required=True)  # Must exist
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
        raise ValidationError({"_entity": ["Balance cannot be below overdraft limit"]})
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

Protean checks invariants at these points:

1. **At the end of `__init__`**: post-invariants run once the new instance is
   built. Pre-invariants do not run here.
2. **On every field assignment**: pre-invariants run before the new value is
   set, and post-invariants run after it. A method that changes state is checked
   at each assignment it makes. A change to a child entity (adding, removing, or
   setting a field on it) checks the invariants on the aggregate root as well.
3. **At the end of an `atomic_change` block**: `with atomic_change(account):`
   (`from protean import atomic_change`) runs the pre-invariants once at the
   start and defers the post-invariants to the end of the block. Use it when
   several fields must change together and are invalid in between.

`repository.add()` does not check invariants again. A broken rule raises at the
assignment that breaks it, before the aggregate reaches the repository.

```python
from protean import atomic_change

domain.init(traverse=False)

with domain.domain_context():
    # Checked at the end of __init__
    try:
        Account(account_number="ACC-1", balance="-500.00", overdraft_limit="100.00")
    except ValidationError as exc:
        print(exc.messages)  # {'_entity': [...]}

    # Checked on the assignment inside withdraw()
    account = Account(account_number="ACC-2", balance="1000.00", overdraft_limit="100.00")
    try:
        account.withdraw(D("1200.00"))
    except ValidationError as exc:
        print(exc.messages)

    # Checked on a direct field change
    account = Account(account_number="ACC-3", balance="500.00", overdraft_limit="100.00")
    try:
        account.balance = D("-200.00")  # Raises here, not when the account is persisted
    except ValidationError as exc:
        print(exc.messages)

    # Deferred to the end of the block
    account = Account(account_number="ACC-4", balance="500.00", overdraft_limit="100.00")
    with atomic_change(account):
        account.balance = D("-800.00")  # Invalid for now, not checked yet
        account.overdraft_limit = D("1000.00")  # Valid again when the block ends
```

## Best Practices

1. **Name invariants descriptively** - Method name should explain the rule
2. **Raise the dict form of `ValidationError`** - Key it by the field at fault, or `_entity` for a rule that compares fields
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
            raise ValidationError({"line_items": ["Placed order must have items"]})
        if not self.payment_info:
            raise ValidationError({"payment_info": ["Placed order must have payment"]})
    if self.status == "shipped":
        if not self.shipping_info:
            raise ValidationError(
                {"shipping_info": ["Shipped order must have shipping info"]}
            )
```

### Invariant with Helper Method

```python
@domain.entity(part_of="ShoppingCart")
class CartItem:
    sku: String(required=True)
    quantity: Integer(default=1, min_value=1)


@domain.aggregate
class ShoppingCart:
    items = HasMany("CartItem")
    max_items: Integer(default=50)

    def _total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @invariant.post
    def cart_cannot_exceed_max_items(self):
        if self._total_quantity() > self.max_items:
            raise ValidationError(
                {"_entity": [f"Cart cannot exceed {self.max_items} items"]}
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
import pytest


def test_account_overdraft_invariant():
    account = Account(account_number="ACC-1", balance="1000.00", overdraft_limit="100.00")

    # Should succeed
    account.withdraw(D("1000.00"))
    assert account.balance == D("0")

    # Should fail
    with pytest.raises(ValidationError) as exc:
        account.withdraw(D("200.00"))
    assert "INVARIANT_POST_FAILED" in exc.value.codes
    assert "_entity" in exc.value.messages
```

## Related

- [Anti-patterns](./anti-patterns.md) - Common invariant mistakes
- [domain-service](../../domain-service/SKILL.md) - Cross-aggregate invariants
