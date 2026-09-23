# Basic Validators

Build custom callable validator classes for format validation from scratch.

## Overview

A custom validator is any callable class that:
1. Has an `__init__` method to configure error messages
2. Has a `__call__` method that receives the field value
3. Raises `ValidationError` (from `protean.exceptions`) if validation fails
4. Returns nothing on success

## Code

The complete implementation is in [assets/custom_validator_basic.py](../assets/custom_validator_basic.py).

Key highlights:
- `PhoneValidator` validates E.164-like phone numbers (+ prefix, 10-15 digits)
- `UrlValidator` validates HTTP/HTTPS URLs with domain check
- Both are attached to value objects via `validators=[ValidatorInstance()]`
- Validators strip formatting characters before checking core format

## Walkthrough

### PhoneValidator

The phone validator demonstrates a common pattern: **strip formatting, then validate structure**.

```python
class PhoneValidator:
    def __init__(self):
        self.error = "Invalid phone number..."

    def __call__(self, value):
        cleaned = value.replace("-", "").replace(" ", "")...
        if not cleaned.startswith("+"):
            raise ValidationError(self.error)
        digits = cleaned[1:]
        if not digits.isdigit() or not (10 <= len(digits) <= 15):
            raise ValidationError(self.error)
```

Design decisions:
- Strips common separators (dashes, spaces, parens) before validation
- Requires international prefix (+) for unambiguous formatting
- Validates digit count range (10-15) per E.164 standard

### UrlValidator

The URL validator checks structural validity without external libraries:

```python
class UrlValidator:
    VALID_SCHEMES = ("http://", "https://")

    def __call__(self, value):
        if not any(value.startswith(scheme) for scheme in self.VALID_SCHEMES):
            raise ValidationError(self.error)
        without_scheme = value.split("://", 1)[1]
        if not without_scheme or without_scheme.startswith("/"):
            raise ValidationError(self.error)
        domain_part = without_scheme.split("/")[0].split(":")[0]
        if "." not in domain_part:
            raise ValidationError(self.error)
```

Design decisions:
- Only allows http/https schemes (not ftp, file, etc.)
- Checks for domain presence and basic structure
- Handles port numbers by stripping `:port` before domain check

## Validator Anatomy

Every custom validator follows this pattern:

```python
from protean.exceptions import ValidationError

class MyValidator:
    """Description of what this validates."""

    def __init__(self):
        self.error = "Clear error message describing what went wrong"

    def __call__(self, value):
        """value is already type-cast by the field."""
        if not is_valid(value):
            raise ValidationError(self.error)
```

## Testing

Test validators both in isolation and within domain elements:

```python
# Test validator directly
def test_valid_phone():
    validator = PhoneValidator()
    validator("+1-555-123-4567")  # Should not raise

def test_invalid_phone():
    validator = PhoneValidator()
    with pytest.raises(ValidationError):
        validator("555-1234")  # Missing + prefix

# Test via value object
def test_phone_value_object():
    phone = Phone(number="+1-555-123-4567")
    assert phone.number == "+1-555-123-4567"
```

## Related

- [Regex Validators](./regex-validators.md) - Pattern-based alternative
- [Parameterized Validators](./parameterized-validators.md) - Making validators configurable
