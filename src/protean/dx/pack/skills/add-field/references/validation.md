# Validation Strategies

This guide explains when and how to validate field data in Protean.

## Overview

Protean provides three levels of validation:
1. **Field-level validation** - Built-in parameters and custom validators
2. **Invariants** - Business rules enforced on aggregates/entities/value objects
3. **Method-level validation** - Parameter validation in methods

## Field-Level Validation

Field-level validation is the first line of defense. Use it for data type constraints and format requirements.

### Built-in Field Parameters

All fields support these validation parameters:

```python
from protean.fields import Decimal, Float, Integer, String

@domain.aggregate
class Product:
    # Required vs optional
    name: String(required=True)        # Must be provided
    description: String()              # Optional (can be None)

    # Default values
    status: String(default="draft")    # Used when not provided

    # Uniqueness
    sku: String(unique=True)           # Must be unique

    # Choices (enum-like)
    category: String(choices=["electronics", "clothing", "food"])
```

### Type-Specific Parameters

**String/Text validation**:
```python
# Length constraints
name: String(max_length=100, min_length=3)
description: Text()  # No length limit

# Sanitization is opt-in per field, or domain-wide via [field_defaults] sanitize
user_input: String(sanitize=True)  # Opt-in: the default is off
```

**Integer/Decimal/Float validation**:
```python
# Range constraints
price: Decimal(precision=19, scale=4, min_value=0.01, max_value=999999.99)
quantity: Integer(min_value=1, max_value=1000)
discount: Float(min_value=0.0, max_value=100.0)

# Temperature (can be negative)
temperature: Float(min_value=-273.15)
```

**When to use built-in parameters**:
- Data type constraints (length, range)
- Required/optional status
- Uniqueness constraints
- Simple format rules

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

**When to use custom validators**:
- Complex format validation (email, phone, URLs)
- Domain-specific rules for single fields
- Reusable validation logic

See [../assets/add_field_with_custom_validator.py](../assets/add_field_with_custom_validator.py) for complete example.

## Invariants (Business Rules)

Invariants are business rules enforced on domain elements. Use them for cross-field validations and complex domain logic.

### When to Use Invariants

**Use invariants for**:
- Cross-field validations (end_date > start_date)
- Complex business rules involving multiple attributes
- State-dependent validations
- Domain constraints that span multiple fields

**DON'T use invariants for**:
- Simple data type constraints (use field parameters)
- Single-field format validation (use custom validators)
- Method parameter validation

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

`repository.add()` does not re-check them. A failed post invariant raises at the change, but
the invalid value stays on the object, so discard the object instead of persisting it.

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

1. **One rule per invariant** - Keep them granular
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

2. **Use descriptive names** - Name should describe the rule
```python
# Good
@invariant.post
def discount_cannot_exceed_total_price(self):
    ...

# Bad
@invariant.post
def validate_discount(self):
    ...
```

3. **Prefer post over pre** - Use post for most validations
```python
# Good: Post invariant for final state
@invariant.post
def end_date_must_be_after_start_date(self):
    ...

# Use pre only for preconditions
@invariant.pre
def account_must_be_active_for_changes(self):
    ...
```

## Validation Strategy: Decision Tree

Use this decision tree to choose the right validation approach:

```
What are you validating?

Single field constraint?
├─ Data type? (length, range, required)
│  └─ Use field parameters: min_value, max_value, max_length, required
├─ Format? (email, phone, custom)
│  └─ Use custom field validator
└─ Continue

Multiple fields?
├─ Cross-field business rule? (end > start)
│  └─ Use @invariant.post
├─ State-dependent rule?
│  └─ Use @invariant.post or @invariant.pre
└─ Continue

Method parameter?
└─ Validate in method body
```

## Examples

### Example 1: Field Parameters (Simple Constraints)

```python
@domain.aggregate
class Product:
    # Use field parameters for data type constraints
    name: String(required=True, min_length=3, max_length=200)
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01, max_value=999999.99)
    stock_count: Integer(default=0, min_value=0)
    status: String(choices=["draft", "active", "discontinued"])
```

### Example 2: Custom Validator (Format Validation)

```python
class PhoneValidator:
    """Validate phone number format."""

    def __call__(self, value: str):
        # Remove common formatting
        digits = ''.join(c for c in value if c.isdigit())

        # Must be 10 digits
        if len(digits) != 10:
            raise ValidationError("Phone must be 10 digits")

        # Cannot start with 0 or 1
        if digits[0] in ['0', '1']:
            raise ValidationError("Phone cannot start with 0 or 1")


@domain.aggregate
class Customer:
    phone: String(
        required=True,
        validators=[PhoneValidator()]
    )
```

### Example 3: Invariants (Cross-Field Rules)

```python
@domain.aggregate
class Subscription:
    start_date: Date(required=True)
    end_date: Date(required=True)
    trial_days: Integer(default=0, min_value=0)
    is_active: Boolean(default=False)

    @invariant.post
    def end_date_must_be_after_start_date(self):
        """Granular rule: date ordering."""
        if self.end_date <= self.start_date:
            raise ValidationError({"_entity": ["End date must be after start date"]})

    @invariant.post
    def active_subscription_must_have_valid_dates(self):
        """Granular rule: active requires valid dates."""
        if self.is_active:
            from datetime import date
            today = date.today()
            if today < self.start_date or today > self.end_date:
                raise ValidationError(
                    {"_entity": ["Active subscription must be within date range"]}
                )

    @invariant.post
    def trial_period_must_fit_within_subscription(self):
        """Granular rule: trial period constraint."""
        days_diff = (self.end_date - self.start_date).days
        if self.trial_days > days_diff:
            raise ValidationError(
                {"_entity": ["Trial period exceeds subscription duration"]}
            )
```

### Example 4: Method Parameter Validation

```python
@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0, min_value=0)  # Field constraint

    @invariant.post
    def balance_must_not_be_negative(self):
        """Invariant: balance state constraint."""
        if self.balance < 0:
            raise ValidationError({"balance": ["Insufficient funds"]})

    def withdraw(self, amount: D):
        """Withdraw money from account."""
        # Parameter validation in method
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > 10000:
            raise ValueError("Withdrawal exceeds daily limit")

        # Update state (invariant checked automatically)
        self.balance -= amount
```

## Common Validation Patterns

### Pattern 1: Email Validation

```python
class EmailValidator:
    """Basic email format validation."""

    def __call__(self, value: str):
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValidationError("Invalid email format")

        local, domain = value.rsplit("@", 1)
        if not local or not domain or "." not in domain:
            raise ValidationError("Invalid email format")


@domain.aggregate
class User:
    email: String(
        required=True,
        max_length=254,
        validators=[EmailValidator()]
    )
```

### Pattern 2: Price Validation

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

### Pattern 3: Date Range Validation

```python
@domain.value_object
class DateRange:
    start_date: Date(required=True)
    end_date: Date(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        """Date ordering rule."""
        if self.end_date <= self.start_date:
            raise ValidationError({"_entity": ["End date must be after start date"]})

    @property
    def duration_days(self) -> int:
        """Calculate duration in days."""
        return (self.end_date - self.start_date).days
```

### Pattern 4: Conditional Validation

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

## Anti-Patterns

### Anti-Pattern 1: Manual Validation Instead of Field Parameters

**Bad**:
```python
@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4)  # No validation!

    def set_price(self, new_price: D):
        if new_price <= 0:  # Manual validation
            raise ValueError("Price must be positive")
        self.price = new_price
```

**Good**:
```python
@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01)  # Field handles it

    def set_price(self, new_price: D):
        self.price = new_price  # Field validates automatically
```

### Anti-Pattern 2: Invariants for Single-Field Constraints

**Bad**:
```python
@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4)

    @invariant.post  # Wrong! Use field parameter
    def price_must_be_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})
```

**Good**:
```python
@domain.aggregate
class Product:
    price: Decimal(required=True, precision=19, scale=4, min_value=0.01)  # Field parameter
```

### Anti-Pattern 3: Multiple Rules in One Invariant

**Bad**:
```python
@invariant.post
def validate_order(self):  # Too many rules!
    if not self.line_items:
        raise ValidationError({"line_items": ["Order must have items"]})
    if self.total < 0:
        raise ValidationError({"total": ["Total cannot be negative"]})
    if self.status == "shipped" and not self.tracking:
        raise ValidationError({"tracking": ["Shipped needs tracking"]})
```

**Good**:
```python
@invariant.post
def order_must_have_items(self):
    if not self.line_items:
        raise ValidationError({"line_items": ["Order must have items"]})

@invariant.post
def order_total_must_not_be_negative(self):
    if self.total < 0:
        raise ValidationError({"total": ["Total cannot be negative"]})

@invariant.post
def shipped_order_must_have_tracking(self):
    if self.status == "shipped" and not self.tracking:
        raise ValidationError({"tracking": ["Shipped needs tracking"]})
```

## Summary

**Use field-level validation for**:
- Data type constraints (length, range, required)
- Single-field format validation (with custom validators)
- Uniqueness constraints

**Use invariants for**:
- Cross-field business rules
- Complex domain logic
- State-dependent validations

**Use method validation for**:
- Method parameter constraints
- Operation-specific validations

## See Also

- [Field Types Guide](field-types.md) - Available field types
- [Complete validator example](../assets/add_field_with_custom_validator.py)
- [Protean documentation on validators](https://docs.proteanhq.com/reference/fields/arguments/#validators)
