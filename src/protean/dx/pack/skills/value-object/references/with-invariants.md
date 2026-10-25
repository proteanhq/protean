# Value Objects with Invariants

An `@invariant.post` method checks a rule that spans several fields of a value object. It runs after the value object is built and raises `ValidationError` in the dict form, `ValidationError({"<field>": ["<message>"]})`, when the rule fails.

## Code

The complete implementation is in [assets/value_object_with_invariants.py](../assets/value_object_with_invariants.py).

## Walkthrough

### Simple Invariant

```python
from protean.exceptions import ValidationError


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        """Business rule: USD balances cannot be negative."""
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError(
                {"balance": ["Balance cannot be negative for USD"]}
            )
```

The rule reads two fields, `currency` and `amount`, so it cannot be a field validator.

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

Every invariant runs, in definition order, even after one fails. The messages of all the failing invariants are collected into one `ValidationError`, keyed by field.

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

The rule reads one field: a format, a range or a choice. See [Value Objects with Validation](./with-validation.md).

### Use Invariants When:

The rule reads two or more fields, or one field's rule depends on another's value.

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

```python
from decimal import Decimal as D

import pytest


def test_valid_usd_balance():
    # Positive USD balance is valid
    balance = Balance(currency="USD", amount=D("100.00"))
    assert balance.amount == D("100.00")

def test_negative_usd_balance_fails():
    # Negative USD balance violates invariant
    with pytest.raises(ValidationError) as exc:
        Balance(currency="USD", amount=D("-100.00"))
    assert "Balance cannot be negative for USD" in str(exc.value)

def test_negative_eur_balance_allowed():
    # Negative EUR balance is allowed (different rule)
    balance = Balance(currency="EUR", amount=D("-50.00"))
    assert balance.amount == D("-50.00")
```

## Common Mistakes

**Missing @invariant.post decorator** ❌
```python
# fragment
def check_something(self):  # Won't run automatically!
    if self.amount < 0:
        raise ValidationError(...)
```

**Not raising ValidationError** ❌
```python
# fragment
@invariant.post
def check_something(self):
    if self.amount < 0:
        return False  # Wrong! Should raise ValidationError
```

## Invariants vs Methods

Invariants enforce rules at creation time. Methods validate operations:

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

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

- [Value Objects with Validation](./with-validation.md): Field-level validation
- [Value Objects with Methods](./with-methods.md): Adding behavior
- [Anti-patterns](./anti-patterns.md): Common mistakes
