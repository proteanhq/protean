# Validation Strategies

The SKILL.md, step 4, picks the validation layer for a rule. This page holds the detail
for each layer.

## Field-Level Validation

### Built-in Field Parameters

All fields take `required`, `default`, `unique` and `choices`. The SKILL.md, step 3, shows
each one.

### Type-Specific Parameters

**String/Text validation**:
```python
# Length constraints
name: String(max_length=100, min_length=3)
description: Text()  # No length limit

# Sanitization is opt-in per field, or domain-wide via [field_defaults] sanitize
user_input: String(sanitize=True)  # Opt-in: the default is off
```

### Custom Field Validators

For complex single-field validations, create custom validators:

```python
from protean.exceptions import ValidationError

class EmailDomainValidator:
    """Validate email belongs to specific domain."""

    def __init__(self, domain="example.com"):
        self.domain = domain
        self.message = f"Email must belong to {self.domain}"

    def __call__(self, value: str):
        if not value.endswith(f"@{self.domain}"):
            raise ValidationError(self.message)


@domain.aggregate
class Employee:
    email: String(
        required=True,
        max_length=254,
        validators=[EmailDomainValidator("company.com")]
    )
```

**Validator structure**:
1. Class with `__init__` for configuration
2. `__call__` method that takes the field value
3. Raises `ValidationError` on invalid data

**Multiple validators** run in the order you list them:
```python
from protean.fields.validators import RegexValidator

@domain.aggregate
class Contractor:
    email: String(
        required=True,
        max_length=254,
        validators=[
            RegexValidator(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
            EmailDomainValidator("company.com"),
        ]
    )
```

See [../assets/add_field_with_custom_validator.py](../assets/add_field_with_custom_validator.py) for complete example.

## Invariants (Business Rules)

Use invariants for cross-field rules and state-dependent rules.

### Post Invariants

Post invariants check state AFTER changes:

```python
from protean import invariant
from protean.exceptions import ValidationError

@domain.aggregate
class DateRange:
    start_date: Date(required=True)
    end_date: Date(required=True)

    @invariant.post
    def end_date_must_be_after_start_date(self):
        """Granular business rule: date ordering.

        Checked after initialization and after any attribute changes.
        """
        if self.end_date < self.start_date:
            raise ValidationError({"_entity": ["End date must be after start date"]})
```

**When post invariants run**:
- After object initialization
- After any attribute change (on the aggregate root too, when a child entity changes)
- At the end of a `with atomic_change(obj):` block, when you group several changes

`repository.add()` does not re-check them. A failed post invariant raises at the change and
rolls it back, so the object keeps the values it had before the change.

### Pre Invariants

Pre invariants check state BEFORE changes (not during initialization):

```python
from decimal import Decimal as D

@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0)
    status: String(default="active")

    @invariant.pre
    def account_must_be_active(self):
        """Pre-check before allowing state changes.

        NOT checked during initialization, only before updates.
        """
        if self.status != "active":
            raise ValidationError({"status": ["Account is not active"]})

    def withdraw(self, amount: D):
        self.balance -= amount  # Pre invariant checked before this
```

**When pre invariants run**:
- Before attribute changes (NOT during initialization)
- At the start of a `with atomic_change(obj):` block, when you group several changes

### Best Practices for Invariants

1. **One rule per invariant**: Keep them granular
```python
# Good: One rule
@invariant.post
def balance_must_not_be_negative(self):
    if self.balance < 0:
        raise ValidationError({"balance": ["Balance cannot be negative"]})

# Good: Another single rule
@invariant.post
def balance_must_not_exceed_limit(self):
    if self.balance > self.max_balance:
        raise ValidationError({"_entity": ["Balance exceeds limit"]})

# Bad: Multiple rules in one invariant
@invariant.post
def balance_rules(self):
    if self.balance < 0:
        raise ValidationError({"balance": ["Balance cannot be negative"]})
    if self.balance > self.max_balance:
        raise ValidationError({"_entity": ["Balance exceeds limit"]})
```

2. **Name the rule**: `discount_cannot_exceed_total_price`, not `validate_discount`.

3. **Prefer post over pre**: Check the final state with `@invariant.post`. Use
   `@invariant.pre` only for a precondition on a change.

## Examples

### Example 1: Method Parameter Validation

```python
@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0, min_value=0)  # Field constraint

    def withdraw(self, amount: D):
        """Withdraw money from account."""
        # Parameter validation in method
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > 10000:
            raise ValueError("Withdrawal exceeds daily limit")

        # Update state (the field rejects a negative balance)
        self.balance -= amount
```

## Common Validation Patterns

### Pattern 1: Price Validation

```python
@domain.aggregate
class Product:
    # Field-level: positive price
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01)
    # A Decimal too, because it feeds money arithmetic
    discount_percent: Decimal(precision=5, scale=2, default=0, min_value=0, max_value=100)

    @invariant.post
    def discounted_price_must_be_positive(self):
        """Cross-field: ensure discount doesn't make price negative."""
        discount_amount = self.price * (self.discount_percent / 100)
        final_price = self.price - discount_amount
        if final_price <= 0:
            raise ValidationError(
                {"_entity": ["Discount cannot reduce price to zero or below"]}
            )
```

### Pattern 2: Conditional Validation

```python
@domain.aggregate
class Order:
    status: String(choices=["draft", "placed", "shipped", "delivered"])
    tracking_number: String()
    delivery_date: Date()

    @invariant.post
    def shipped_orders_must_have_tracking(self):
        """Conditional: shipped requires tracking."""
        if self.status in ["shipped", "delivered"] and not self.tracking_number:
            raise ValidationError(
                {"tracking_number": ["Shipped orders must have tracking number"]}
            )

    @invariant.post
    def delivered_orders_must_have_delivery_date(self):
        """Conditional: delivered requires date."""
        if self.status == "delivered" and not self.delivery_date:
            raise ValidationError(
                {"delivery_date": ["Delivered orders must have delivery date"]}
            )
```

## See Also

- [Field Types Guide](field-types.md): Available field types
- [Complete validator example](../assets/add_field_with_custom_validator.py)
- [Protean documentation on validators](https://docs.proteanhq.com/reference/fields/arguments/#validators)
