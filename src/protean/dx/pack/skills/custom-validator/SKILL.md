---
name: custom-validator
description: Build custom field validators for Protean domain elements — callable classes that validate individual field values. Covers format validation (email, phone, URL, SKU, credit card, etc.), using Protean's built-in RegexValidator, creating parameterized/configurable validators, composing multiple validators on a single field, and customizing error messages. Use when the user asks to "create a validator", "add custom validation", "validate email format", "validate phone number", "build a format checker", "add a regex validator", or needs single-field validation beyond built-in constraints (required, max_length, min_value, choices). Custom validators are callable classes attached to fields via the validators=[] parameter and raise ValidationError on invalid input.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Custom Validator

Custom validators are callable classes that validate individual field values. They are the mechanism for enforcing format rules, patterns, and domain-specific constraints on a single field — beyond what built-in field parameters (`required`, `max_length`, `min_value`, `choices`) provide.

## Basic structure

A custom validator is a callable class with `__call__` that raises `ValidationError` on invalid input:

```python
from protean.exceptions import ValidationError

class PhoneValidator:
    """Validates phone number format."""

    def __init__(self):
        self.error = "Invalid phone number format"

    def __call__(self, value):
        cleaned = value.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        if not cleaned.startswith("+"):
            raise ValidationError(self.error)
        digits = cleaned[1:]
        if not digits.isdigit() or not (10 <= len(digits) <= 15):
            raise ValidationError(self.error)
```

Attach to a field with the `validators` parameter:

```python
@domain.value_object
class Phone:
    number: String(required=True, max_length=20, validators=[PhoneValidator()])
```

## Key rules

1. **Validators are callable classes** — Implement `__init__` and `__call__`. The `__call__` method receives the field value as its single argument.
2. **Raise `ValidationError` on failure** — Import from `protean.exceptions`. The error message string gets wrapped into `{field_name: [message]}` automatically.
3. **Return nothing on success** — If the value is valid, simply return (no return value needed).
4. **Validators run AFTER type casting** — The value passed to `__call__` has already been cast to the field's native type (e.g., `str` for `String`, `int` for `Integer`).
5. **Multiple validators are chained** — Use `validators=[V1(), V2()]`; all validators run, errors are collected.
6. **Validators are for single-field rules** — For cross-field validation, use `@invariant.post` instead (see [add-validation](../add-validation/SKILL.md)).
7. **Keep validators reusable** — Make them configurable via `__init__` parameters so they work across multiple fields and domain elements.

## Validation execution order

When a field value is set, Protean validates in this order:

1. **Empty check** — `required` field without value raises error
2. **Choices check** — Value must be in `choices` enum/list
3. **Type casting** — `_cast_to_type()` converts to native type
4. **Validators** — All validators in `validators=[]` list run sequentially

Custom validators execute at step 4, after the value is already type-cast and choice-validated.

## Built-in validators

Protean provides these validators out of the box (used internally by fields):

| Validator | Used by | Purpose |
|-----------|---------|---------|
| `MinLengthValidator(n)` | `String(min_length=n)` | Minimum character count |
| `MaxLengthValidator(n)` | `String(max_length=n)` | Maximum character count |
| `MinValueValidator(n)` | `Integer(min_value=n)`, `Float(min_value=n)` | Minimum numeric value |
| `MaxValueValidator(n)` | `Integer(max_value=n)`, `Float(max_value=n)` | Maximum numeric value |

These are applied automatically — you don't need to add them to `validators=[]`.

## Using RegexValidator

For pattern-based validation, use Protean's built-in `RegexValidator`:

```python
from protean.fields.validators import RegexValidator

@domain.value_object
class ProductCode:
    code: String(
        required=True,
        max_length=10,
        validators=[
            RegexValidator(
                regex=r"^[A-Z]{3}-\d{4}$",
                message="Product code must be in format XXX-9999"
            )
        ]
    )
```

`RegexValidator` supports:
- `regex` — Pattern string or compiled regex
- `message` — Custom error message (default: "invalid value")
- `inverse_match` — If `True`, fails when pattern DOES match
- `flags` — Regex flags (only when `regex` is a string)

## Parameterized validators

Make validators configurable via constructor parameters:

```python
class AllowedDomainValidator:
    """Validates email belongs to allowed domains."""

    def __init__(self, allowed_domains):
        self.allowed_domains = allowed_domains
        self.error = f"Email must belong to one of: {', '.join(allowed_domains)}"

    def __call__(self, value):
        domain_part = value.split("@")[-1].lower()
        if domain_part not in self.allowed_domains:
            raise ValidationError(self.error)

# Reuse with different configurations
corporate_email: String(validators=[AllowedDomainValidator(["company.com", "corp.com"])])
partner_email: String(validators=[AllowedDomainValidator(["partner.org", "vendor.net"])])
```

## Composing multiple validators

Chain validators for layered validation — all validators run and errors are collected:

```python
@domain.value_object
class Username:
    value: String(
        required=True,
        min_length=3,
        max_length=30,
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z][a-zA-Z0-9_]*$",
                message="Username must start with a letter, only letters/digits/underscores"
            ),
            ReservedWordValidator(reserved=["admin", "root", "system"]),
        ]
    )
```

## Common mistakes

- **Raising `ValueError` instead of `ValidationError`** — Always use `from protean.exceptions import ValidationError`. `ValueError` will not be caught by Protean's validation pipeline correctly.
- **Using validators for cross-field rules** — Validators only see one field's value. For rules involving multiple fields (e.g., "end_date > start_date"), use `@invariant.post` instead.
- **Duplicating built-in constraints** — Don't write a validator for `min_length` or `max_value` — use the field's built-in parameters.
- **Not making validators reusable** — Pass configuration through `__init__`, not hardcoded values.

## Complete examples

- [Basic validators (phone, URL)](assets/custom_validator_basic.py)
- [RegexValidator usage](assets/custom_validator_regex.py)
- [Parameterized validators](assets/custom_validator_parameterized.py)
- [Composing multiple validators](assets/custom_validator_composition.py)

## Detailed references

- [Basic Validators](references/basic-validators.md) - Building callable validator classes from scratch
- [Regex Validators](references/regex-validators.md) - Using Protean's RegexValidator for pattern matching
- [Parameterized Validators](references/parameterized-validators.md) - Configurable validators with constructor params
- [Composing Validators](references/composing-validators.md) - Chaining validators and error message customization
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

## Related skills

- [value-object](../value-object/SKILL.md) - Value objects often use custom validators
- [add-field](../add-field/SKILL.md) - Adding fields with validation to domain elements
- [add-validation](../add-validation/SKILL.md) - Choosing the right validation layer (field vs invariant vs guard)
- [aggregate](../aggregate/SKILL.md) - Aggregates can use field validators too

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
