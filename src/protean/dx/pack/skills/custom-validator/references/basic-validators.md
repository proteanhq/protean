# Basic Validators

Two format validators built from scratch, `PhoneValidator` and `UrlValidator`. SKILL.md "Basic structure" and "Key rules" give the anatomy every validator follows.

## Code

The complete implementation is in [assets/custom_validator_basic.py](../assets/custom_validator_basic.py).

## Walkthrough

### PhoneValidator

The phone validator demonstrates a common pattern: **strip formatting, then validate structure**.

```python
from protean.exceptions import ValidationError


class PhoneValidator:
    def __init__(self):
        self.error = "Invalid phone number. Must start with + followed by 10-15 digits"

    def __call__(self, value):
        cleaned = (
            value.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        )
        if not cleaned.startswith("+"):
            raise ValidationError(self.error)
        digits = cleaned[1:]
        if not digits.isdigit() or not (10 <= len(digits) <= 15):
            raise ValidationError(self.error)
```

It requires the international `+` prefix and 10 to 15 digits, the E.164 range. Call it on two valid numbers and two invalid ones. `"+1 (555) 123-4567"` passes once the separators are stripped. `"1-555-123-4567"` has the right digits but no `+` prefix, and `"+1234"` has the prefix but too few digits, so both raise:

```python
validator = PhoneValidator()
validator("+1-555-123-4567")  # passes
validator("+1 (555) 123-4567")  # passes: parens and spaces are stripped

for invalid in ["1-555-123-4567", "+1234"]:
    try:
        validator(invalid)
    except ValidationError:
        pass
    else:
        raise AssertionError(f"{invalid} should be rejected")
```

Attach it to a field with the `validators` parameter:

```python
@domain.value_object
class Phone:
    number: String(required=True, max_length=30, validators=[PhoneValidator()])
```

### UrlValidator

The URL validator checks structural validity without external libraries:

```python
class UrlValidator:
    VALID_SCHEMES = ("http://", "https://")

    def __init__(self):
        self.error = "Invalid URL. Must start with http:// or https://"

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

## Related

- [Regex Validators](./regex-validators.md): Pattern-based alternative
- [Parameterized Validators](./parameterized-validators.md): Making validators configurable
