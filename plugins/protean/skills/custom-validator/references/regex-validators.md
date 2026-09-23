# Regex Validators

Use Protean's built-in `RegexValidator` for pattern-based field validation.

## Overview

When your validation rule can be expressed as a regular expression, use `RegexValidator` instead of writing a custom callable class. It handles regex compilation, matching, and error reporting.

## Code

The complete implementation is in [assets/custom_validator_regex.py](../assets/custom_validator_regex.py).

Key highlights:
- SKU format validation (`XXX-9999`)
- Hex color code validation (`#RRGGBB`)
- US postal code validation (5-digit or 5+4 format)
- Inverse match for deny-list patterns (profanity blocking)

## RegexValidator API

```python
from protean.fields.validators import RegexValidator

RegexValidator(
    regex=r"^pattern$",      # Pattern string or compiled regex
    message="Error message",  # Custom error (default: "invalid value")
    inverse_match=False,      # True = fail when pattern MATCHES
    flags=0,                  # Regex flags (re.IGNORECASE, etc.)
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `regex` | str or Pattern | `""` | Regular expression to match against |
| `message` | str | `"invalid value"` | Error message on validation failure |
| `inverse_match` | bool | `False` | If True, validation fails when pattern matches |
| `flags` | int | `0` | Regex flags (only when regex is a string) |

## Common Patterns

### Product/SKU codes
```python
RegexValidator(regex=r"^[A-Z]{3}-\d{4}$", message="Format: XXX-9999")
```

### Hex colors
```python
RegexValidator(regex=r"^#[0-9A-Fa-f]{6}$", message="Format: #RRGGBB")
```

### Postal codes (US)
```python
RegexValidator(regex=r"^\d{5}(-\d{4})?$", message="Format: 99999 or 99999-9999")
```

### Alphanumeric codes
```python
RegexValidator(regex=r"^[A-Za-z0-9]+$", message="Only letters and digits allowed")
```

### Deny-list (inverse match)
```python
RegexValidator(
    regex=r"(badword|offensive)",
    message="Contains prohibited content",
    inverse_match=True,  # Fails when pattern IS found
)
```

## When to Use RegexValidator vs Custom Class

**Use RegexValidator when**:
- Validation is purely pattern matching
- A single regex can express the rule
- No complex logic needed (just match/no-match)

**Use custom validator class when**:
- Validation requires multi-step logic (strip, check, compute)
- You need access to external data or configuration
- The rule cannot be expressed as a single regex
- You need to preprocess the value before pattern matching

## Related

- [Basic Validators](./basic-validators.md) - Custom callable classes
- [Composing Validators](./composing-validators.md) - Combining regex with custom validators
