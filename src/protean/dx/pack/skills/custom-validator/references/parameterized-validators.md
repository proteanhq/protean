# Parameterized Validators

Create configurable, reusable validators with constructor parameters.

## Overview

Parameterized validators accept configuration in their `__init__` method, making them reusable across different fields and domain elements with different requirements. This is the preferred approach for validators that need to be applied with varying rules.

## Code

The complete implementation is in [assets/custom_validator_parameterized.py](../assets/custom_validator_parameterized.py).

Key highlights:
- `AllowedDomainValidator(domains)` - Configurable email domain whitelist
- `LuhnValidator(expected_length)` - Credit card validation with configurable card length
- `StringLengthRangeValidator(min, max, label)` - Reusable length check with custom labels
- Same validator class instantiated with different configs for different fields

## Pattern

```python
class ConfigurableValidator:
    def __init__(self, param1, param2="default"):
        self.param1 = param1
        self.param2 = param2
        # Build error message from params
        self.error = f"Validation failed: expected {param1}"

    def __call__(self, value):
        if not meets_criteria(value, self.param1, self.param2):
            raise ValidationError(self.error)

# Reuse with different configurations
strict_validator = ConfigurableValidator(param1="strict", param2="high")
lenient_validator = ConfigurableValidator(param1="lenient", param2="low")

@domain.aggregate
class StrictEntity:
    field: String(validators=[strict_validator])

@domain.aggregate
class LenientEntity:
    field: String(validators=[lenient_validator])
```

## Walkthrough

### AllowedDomainValidator

Shows how to parameterize a whitelist:

```python
class AllowedDomainValidator:
    def __init__(self, allowed_domains):
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.error = f"Email must belong to one of: {', '.join(self.allowed_domains)}"

    def __call__(self, value):
        domain_part = value.split("@")[-1].lower()
        if domain_part not in self.allowed_domains:
            raise ValidationError(self.error)
```

Usage — same class, different configs:
```python
corporate = AllowedDomainValidator(["company.com", "corp.io"])
partners = AllowedDomainValidator(["partner.org", "vendor.net"])
```

### LuhnValidator

Shows optional parameters with different behavior:

```python
class LuhnValidator:
    def __init__(self, expected_length=None):
        self.expected_length = expected_length
        # Error message adapts to configuration
        if expected_length:
            self.error = f"Must be {expected_length} digits and pass Luhn check"
        else:
            self.error = "Must pass Luhn check"
```

Usage:
```python
visa_validator = LuhnValidator(expected_length=16)  # Visa/MC specific
any_card = LuhnValidator()  # Any valid card number
```

## Best Practices

1. **Normalize in `__init__`** — Lowercase domains, compile patterns, etc.
2. **Build error messages from params** — Dynamic messages are more helpful than static ones
3. **Use sensible defaults** — Optional params should have reasonable defaults
4. **Keep `__call__` focused** — Do setup in `__init__`, validation logic in `__call__`

## Related

- [Basic Validators](./basic-validators.md) - Simple validators without parameters
- [Composing Validators](./composing-validators.md) - Combining parameterized validators
