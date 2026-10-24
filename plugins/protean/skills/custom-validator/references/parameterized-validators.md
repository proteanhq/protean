# Parameterized Validators

A parameterized validator takes its configuration in `__init__`, so one class serves several fields with different rules.

## Code

The complete implementation is in [assets/custom_validator_parameterized.py](../assets/custom_validator_parameterized.py).

## Walkthrough

### AllowedDomainValidator

Unlike the SKILL.md version, this one lowercases the allowed list in `__init__`, so an entry written `"Company.com"` still matches:

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

Usage, with the same class in different configs:
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

1. **Normalize in `__init__`**: Lowercase domains, compile patterns, etc.
2. **Build error messages from params**: Dynamic messages are more helpful than static ones
3. **Use sensible defaults**: Optional params should have reasonable defaults
4. **Keep `__call__` focused**: Do setup in `__init__`, validation logic in `__call__`

## Related

- [Basic Validators](./basic-validators.md): Simple validators without parameters
- [Composing Validators](./composing-validators.md): Combining parameterized validators
