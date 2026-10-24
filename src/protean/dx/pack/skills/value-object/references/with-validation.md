# Value Objects with Validation

A field validator checks one field's value when the value object is built, and raises `ValidationError` when the value is wrong. A rule that needs two fields goes in an `@invariant.post` instead.

## Code

The complete implementation is in [assets/value_object_with_validation.py](../assets/value_object_with_validation.py). Its `EmailValidator` runs more checks than the shorter one below. Among them, an address must have exactly one `@`, a local part of at most 64 characters, domain labels of at most 63 characters that start and end with a letter or digit, and no spaces or unprintable characters.

## Walkthrough

### The Validator Class

```python
from protean.exceptions import ValidationError


class EmailValidator:
    """Custom validator for email address format."""

    def __init__(self):
        self.error = "Invalid email address"

    def __call__(self, value: str):
        """Validate email address according to business rules."""
        if value.count("@") != 1:
            raise ValidationError(self.error)
        local_part, domain_part = value.split("@")
        if not local_part or len(local_part) > 64 or not domain_part:
            raise ValidationError(self.error)
```

The validator is a callable class. The constructor takes its configuration, such as the error message, and `__call__` raises `ValidationError` when the value fails.

### The Value Object

```python
@domain.value_object
class Email:
    address: String(
        max_length=254,
        required=True,
        validators=[EmailValidator()]
    )
```

An aggregate that holds `email = ValueObject(Email)` gets the check with no validation code of its own.

## Validation Patterns

### Field-Level Validation

Use built-in field validators for simple cases:

```python
from protean.fields.validators import RegexValidator


@domain.value_object
class PhoneNumber:
    number: String(
        max_length=20,
        required=True,
        min_length=10,
        validators=[RegexValidator(r'^\+?[1-9]\d{1,14}$')]
    )
```

`String` has no `regex` option. Pattern checks go through `RegexValidator` in the `validators` list.

### Custom Validator Functions

For reusable validation logic:

```python
def validate_not_negative(value):
    if value < 0:
        raise ValidationError("Value must not be negative")

@domain.value_object
class Price:
    amount: Decimal(precision=19, scale=4, required=True, validators=[validate_not_negative])
```

### Validator Classes

For complex, stateful validation:

```python
class RangeValidator:
    def __init__(self, min_val, max_val):
        self.min_val = min_val
        self.max_val = max_val

    def __call__(self, value):
        if not (self.min_val <= value <= self.max_val):
            raise ValidationError(
                f"Value must be between {self.min_val} and {self.max_val}"
            )

@domain.value_object
class Temperature:
    celsius: Float(
        required=True,
        validators=[RangeValidator(-273.15, 5000)]
    )
```

## Common Validation Scenarios

### URLs

```python
class URLValidator:
    def __call__(self, value):
        if not value.startswith(('http://', 'https://')):
            raise ValidationError("URL must start with http:// or https://")
        # Additional URL validation...

@domain.value_object
class WebURL:
    url: String(max_length=2048, validators=[URLValidator()])
```

### Postal Codes

```python
import re

POSTAL_CODE_PATTERNS = {
    'US': r'^\d{5}(-\d{4})?$',
    'UK': r'^[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}$',
    'CA': r'^[A-Z]\d[A-Z]\s?\d[A-Z]\d$'
}


@domain.value_object
class PostalCode:
    code: String(max_length=10, required=True)
    country: String(max_length=2, required=True, choices=list(POSTAL_CODE_PATTERNS))

    @invariant.post
    def code_must_match_country_format(self):
        pattern = POSTAL_CODE_PATTERNS.get(self.country)
        if not pattern or not re.match(pattern, self.code):
            raise ValidationError(
                {"code": [f"Invalid {self.country} postal code"]}
            )
```

A field validator sees one value. The postal code format depends on the country, so the check runs in an `@invariant.post`, which sees every field.

## Testing Validation

Test a valid value and each way a value can be invalid:

```python
import pytest


def test_valid_email():
    email = Email(address="john@example.com")
    assert email.address == "john@example.com"

def test_invalid_email_missing_at():
    with pytest.raises(ValidationError) as exc:
        Email(address="johnexample.com")
    assert "Invalid email address" in str(exc.value)

def test_invalid_email_too_long_local_part():
    with pytest.raises(ValidationError) as exc:
        Email(address="a" * 65 + "@example.com")
    assert "Invalid email address" in str(exc.value)
```

## Related

- [Value Objects with Invariants](./with-invariants.md): For cross-field validation
- [Value Objects with Methods](./with-methods.md): Adding behavior beyond validation
- [Anti-patterns](./anti-patterns.md): Common validation mistakes
