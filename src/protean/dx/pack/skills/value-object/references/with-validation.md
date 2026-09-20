# Value Objects with Validation

Value objects are excellent containers for encapsulating validation logic. When a domain concept has specific rules about what constitutes valid values, implementing it as a value object ensures those rules are enforced consistently throughout your application.

## Overview

Use value objects with validation when:
- A concept has specific format requirements (email, phone, URL)
- Business rules define what constitutes valid values
- You want to prevent invalid data from entering your domain
- Validation logic is complex and should be reusable

## Code

The complete implementation is in [assets/value_object_with_validation.py](../assets/value_object_with_validation.py).

Key points:
- Custom validators encapsulate complex validation logic
- Validators are attached to fields using the `validators` parameter
- ValidationError is raised when rules are violated
- Validation happens at initialization time

## Walkthrough

### The Validator Class

```python
class EmailValidator:
    """Custom validator for email address format."""

    def __init__(self):
        self.error = "Invalid email address"

    def __call__(self, value: str):
        """Validate email address according to business rules."""
        if value.count("@") != 1:
            raise ValidationError(self.error)
        # ... more validation rules
```

The validator is a callable class that:
- Is instantiated with any configuration (like error messages)
- Implements `__call__` to perform the validation
- Raises `ValidationError` if validation fails
- Can contain complex, multi-step validation logic

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

The value object:
- Defines the data structure (single `address` field)
- Attaches the validator via `validators` parameter
- Can have multiple validators in the list
- Ensures all email instances are valid

### Using in Aggregates

```python
@domain.aggregate
class User:
    email = ValueObject(Email, required=True)
    name: String(max_length=100, required=True)
```

Benefits:
- Email validation is automatic - no need to validate in User
- Validation logic is reusable across all email fields
- Cannot create a User with invalid email
- Domain model stays clean and focused

## Validation Patterns

### Field-Level Validation

Use built-in field validators for simple cases:

```python
@domain.value_object
class PhoneNumber:
    number: String(
        max_length=20,
        required=True,
        min_length=10,
        regex=r'^\+?[1-9]\d{1,14}$'
    )
```

### Custom Validator Functions

For reusable validation logic:

```python
def validate_positive(value):
    if value < 0:
        raise ValidationError("Value must be positive")

@domain.value_object
class Price:
    amount: Float(required=True, validators=[validate_positive])
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

### Email Addresses

See the complete example in assets. Key validations:
- Must contain exactly one @ symbol
- Local part max 64 characters
- Domain labels max 63 characters each
- No spaces or unprintable characters
- Must start/end with alphanumeric

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
class PostalCodeValidator:
    def __init__(self, country):
        self.country = country
        self.patterns = {
            'US': r'^\d{5}(-\d{4})?$',
            'UK': r'^[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}$',
            'CA': r'^[A-Z]\d[A-Z]\s?\d[A-Z]\d$'
        }

    def __call__(self, value):
        pattern = self.patterns.get(self.country)
        if not pattern or not re.match(pattern, value):
            raise ValidationError(f"Invalid {self.country} postal code")

@domain.value_object
class PostalCode:
    code: String(max_length=10, required=True)
    country: String(max_length=2, required=True)

    def __post_init__(self):
        # Validate code format for the country
        validator = PostalCodeValidator(self.country)
        validator(self.code)
```

## Testing Validation

Always test both valid and invalid cases:

```python
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

## Best Practices

1. **Keep validators focused** - One validator, one concern
2. **Make error messages clear** - Users need to know what's wrong
3. **Test edge cases** - Validation is where bugs hide
4. **Reuse validators** - Extract common validation to reusable validators
5. **Document validation rules** - Future developers need to understand why
6. **Fail fast** - Validate at construction time, not later

## Related

- [Value Objects with Invariants](./with-invariants.md) - For cross-field validation
- [Value Objects with Methods](./with-methods.md) - Adding behavior beyond validation
- [Anti-patterns](./anti-patterns.md) - Common validation mistakes
