# Value Objects with Invariants

Invariants are business rules that must always be true. When validation spans multiple fields or depends on relationships between attributes, use the `@invariant.post` decorator to enforce these rules at the value object level.

## Overview

Use invariants when:
- Validation depends on multiple fields
- Business rules define relationships between attributes
- Complex domain constraints need enforcement
- You want validation to run automatically on initialization

## Code

The complete implementation is in [assets/value_object_with_invariants.py](../assets/value_object_with_invariants.py).

Key points:
- `@invariant.post` decorator marks validation methods
- Invariants run automatically after initialization
- Raise `ValidationError` when rules are violated
- Can have multiple invariants per value object

## Walkthrough

### Simple Invariant

```python
@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        """Business rule: USD balances cannot be negative."""
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError(
                {"balance": ["Balance cannot be negative for USD"]}
            )
```

This invariant:
- Checks a business rule across two fields (currency and amount)
- Runs automatically after the value object is created
- Prevents creation of invalid balance objects
- Has a clear, descriptive method name

### Multiple Invariants

```python
@domain.value_object
class DiscountPercentage:
    percentage: Float(required=True)
    customer_type: String(max_length=20, required=True)

    @invariant.post
    def percentage_must_be_valid(self):
        """Invariant: Percentage must be between 0 and 100."""
        if not (0 <= self.percentage <= 100):
            raise ValidationError(
                {"discount": ["Discount percentage must be between 0 and 100"]}
            )

    @invariant.post
    def regular_customer_discount_limit(self):
        """Invariant: Regular customers can only get up to 50% discount."""
        if self.customer_type == "regular" and self.percentage > 50:
            raise ValidationError(
                {"discount": ["Regular customers can only receive up to 50% discount"]}
            )
```

Multiple invariants:
- Each checks a specific business rule
- All run in definition order
- All must pass for the value object to be valid
- Each has focused, single-responsibility validation

### Date Range Invariant

```python
@domain.value_object
class DateRange:
    start_date: String(required=True)
    end_date: String(required=True)

    @invariant.post
    def end_date_must_be_after_start_date(self):
        """Invariant: End date must be after or equal to start date."""
        if self.end_date < self.start_date:
            raise ValidationError(
                {"date_range": ["End date must be after or equal to start date"]}
            )
```

## Common Invariant Patterns

### Mutually Exclusive Fields

```python
@domain.value_object
class PaymentMethod:
    credit_card_number: String(max_length=16)
    bank_account_number: String(max_length=20)
    paypal_email: String(max_length=254)

    @invariant.post
    def exactly_one_payment_method_required(self):
        """Must provide exactly one payment method."""
        methods_provided = sum([
            bool(self.credit_card_number),
            bool(self.bank_account_number),
            bool(self.paypal_email)
        ])

        if methods_provided != 1:
            raise ValidationError(
                {"payment_method": ["Exactly one payment method must be provided"]}
            )
```

### Conditional Requirements

```python
@domain.value_object
class ShippingAddress:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(max_length=50)
    postal_code: String(max_length=20)
    country: String(required=True, max_length=50)

    @invariant.post
    def us_addresses_require_state_and_zip(self):
        """US addresses must have state and postal code."""
        if self.country == "USA":
            if not self.state:
                raise ValidationError(
                    {"state": ["State is required for US addresses"]}
                )
            if not self.postal_code:
                raise ValidationError(
                    {"postal_code": ["Postal code is required for US addresses"]}
                )
```

### Range Validation

```python
@domain.value_object
class Temperature:
    celsius: Float(required=True)
    fahrenheit: Float(required=True)

    @invariant.post
    def values_must_be_consistent(self):
        """Celsius and Fahrenheit values must be consistent."""
        expected_fahrenheit = (self.celsius * 9/5) + 32
        tolerance = 0.1

        if abs(self.fahrenheit - expected_fahrenheit) > tolerance:
            raise ValidationError(
                {"temperature": [
                    f"Temperature values inconsistent: "
                    f"{self.celsius}°C should be {expected_fahrenheit}°F, "
                    f"not {self.fahrenheit}°F"
                ]}
            )
```

### Business Logic Constraints

```python
@domain.value_object
class OrderQuantityDiscount:
    quantity: Integer(required=True, min_value=1)
    discount_percentage: Float(required=True, min_value=0, max_value=100)

    @invariant.post
    def bulk_discount_rules(self):
        """Apply business rules for bulk discounts."""
        # 5-9 items: max 10% discount
        if 5 <= self.quantity < 10 and self.discount_percentage > 10:
            raise ValidationError(
                {"discount": ["Orders of 5-9 items can only have up to 10% discount"]}
            )

        # 10-49 items: max 20% discount
        if 10 <= self.quantity < 50 and self.discount_percentage > 20:
            raise ValidationError(
                {"discount": ["Orders of 10-49 items can only have up to 20% discount"]}
            )

        # 50+ items: max 30% discount
        if self.quantity >= 50 and self.discount_percentage > 30:
            raise ValidationError(
                {"discount": ["Orders of 50+ items can only have up to 30% discount"]}
            )
```

### Numeric Relationships

```python
@domain.value_object
class Rectangle:
    length: Float(required=True, min_value=0)
    width: Float(required=True, min_value=0)
    area: Float(required=True, min_value=0)

    @invariant.post
    def area_must_match_dimensions(self):
        """Area must equal length × width."""
        expected_area = self.length * self.width
        tolerance = 0.01

        if abs(self.area - expected_area) > tolerance:
            raise ValidationError(
                {"area": [
                    f"Area {self.area} doesn't match dimensions "
                    f"(should be {expected_area})"
                ]}
            )
```

## Invariants vs Field Validation

### Use Field Validation When:
- Rule applies to single field
- Built-in validators suffice
- Simple type/format checking

```python
@domain.value_object
class Email:
    address: String(
        max_length=254,
        required=True,
        validators=[EmailValidator()]  # Single field
    )
```

### Use Invariants When:
- Rule spans multiple fields
- Conditional validation needed
- Complex business logic
- Field relationships matter

```python
@domain.value_object
class CreditCard:
    number: String(max_length=16, required=True)
    expiry_month: Integer(required=True)
    expiry_year: Integer(required=True)

    @invariant.post
    def card_not_expired(self):
        """Card must not be expired."""
        from datetime import datetime
        now = datetime.now()

        # Multi-field validation
        if self.expiry_year < now.year:
            raise ValidationError({"expiry": ["Card is expired"]})
        if self.expiry_year == now.year and self.expiry_month < now.month:
            raise ValidationError({"expiry": ["Card is expired"]})
```

## Testing Invariants

Test both valid and invalid cases for each invariant:

```python
def test_valid_usd_balance():
    # Positive USD balance is valid
    balance = Balance(currency="USD", amount=100.0)
    assert balance.amount == 100.0

def test_negative_usd_balance_fails():
    # Negative USD balance violates invariant
    with pytest.raises(ValidationError) as exc:
        Balance(currency="USD", amount=-100.0)
    assert "Balance cannot be negative for USD" in str(exc.value)

def test_negative_eur_balance_allowed():
    # Negative EUR balance is allowed (different rule)
    balance = Balance(currency="EUR", amount=-50.0)
    assert balance.amount == -50.0

def test_date_range_valid():
    # End after start is valid
    dr = DateRange(start_date="2024-01-01", end_date="2024-12-31")
    assert dr.end_date > dr.start_date

def test_date_range_invalid():
    # End before start violates invariant
    with pytest.raises(ValidationError) as exc:
        DateRange(start_date="2024-12-31", end_date="2024-01-01")
    assert "End date must be after" in str(exc.value)
```

## Best Practices

1. **Name methods descriptively** - Method name should explain the rule
2. **One rule per method** - Keep invariants focused and testable
3. **Provide clear error messages** - Explain what's wrong and why
4. **Document business rationale** - Explain why the rule exists
5. **Test all branches** - Cover valid and invalid cases
6. **Run on every creation** - Invariants protect data integrity
7. **Use appropriate exception** - Always raise `ValidationError`

## Common Mistakes

**Missing @invariant.post decorator** ❌
```python
def check_something(self):  # Won't run automatically!
    if self.amount < 0:
        raise ValidationError(...)
```

**Not raising ValidationError** ❌
```python
@invariant.post
def check_something(self):
    if self.amount < 0:
        return False  # Wrong! Should raise ValidationError
```

**Vague error messages** ❌
```python
@invariant.post
def check_something(self):
    if self.amount < 0:
        raise ValidationError("Invalid")  # Too vague!
```

**Too many rules in one method** ❌
```python
@invariant.post
def validate_everything(self):
    # Checking 10 different things...
    # Hard to test, hard to maintain
```

## Invariants vs Methods

Invariants enforce rules at creation time. Methods validate operations:

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    @invariant.post
    def amount_must_be_valid(self):
        """Invariant: checked at creation."""
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})

    def add(self, other: "Money") -> "Money":
        """Method: validates during operation."""
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(currency=self.currency, amount=self.amount + other.amount)
```

## Related

- [Value Objects with Validation](./with-validation.md) - Field-level validation
- [Value Objects with Methods](./with-methods.md) - Adding behavior
- [Anti-patterns](./anti-patterns.md) - Common mistakes
