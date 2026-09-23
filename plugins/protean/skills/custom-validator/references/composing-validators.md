# Composing Validators

Chain multiple validators on a single field for layered validation.

## Overview

When a single field needs to satisfy multiple rules (format, business logic, deny-list), compose validators by passing a list to the `validators=[]` parameter. All validators run, and errors from each are collected.

## Code

The complete implementation is in [assets/custom_validator_composition.py](../assets/custom_validator_composition.py).

Key highlights:
- Username validated by 4 different validators (format, reserved words, profanity, consecutive chars)
- Coupon code validated by prefix check + format regex
- Mix of RegexValidator and custom callable classes

## How Composition Works

```python
@domain.aggregate
class UserAccount:
    username: String(
        required=True,
        validators=[
            format_validator,      # Step 1: Check format
            reserved_validator,    # Step 2: Check reserved words
            profanity_validator,   # Step 3: Check profanity
            consecutive_validator, # Step 4: Check consecutive specials
        ],
    )
```

**Execution order**:
1. All validators run in list order
2. Each validator that fails adds its error to the collection
3. After all validators run, collected errors are raised as one `ValidationError`

**Important**: Validators run independently — a failure in one does NOT prevent others from running. This means the user gets all validation errors at once, not one at a time.

## Layered Validation Strategy

Organize validators from general to specific:

```
Layer 1: Format (regex/structural)  → "Must be 3-30 alphanumeric chars"
Layer 2: Business rules             → "Cannot be a reserved word"
Layer 3: Content policy             → "Must not contain profanity"
Layer 4: Style rules                → "No consecutive special chars"
```

## Combining RegexValidator with Custom Validators

```python
from protean.fields.validators import RegexValidator

coupon_validators = [
    # RegexValidator for structural format
    RegexValidator(
        regex=r"^[A-Z]{4}-[A-Z0-9]{4,8}$",
        message="Coupon must be XXXX-YYYY format"
    ),
    # Custom validator for business rule
    PrefixValidator(prefixes=["SAVE", "DISC", "FREE"]),
]

code: String(validators=coupon_validators)
```

## Error Collection

When multiple validators fail, all errors are collected:

```python
# If both format AND reserved word validators fail:
# ValidationError: {
#     "username": [
#         "Must start with a letter, 3-30 chars...",
#         "'admin' is reserved and cannot be used"
#     ]
# }
```

## Best Practices

1. **Order matters for readability** — Put the most common/basic check first
2. **Keep each validator focused** — One rule per validator class
3. **Name validators clearly** — `ReservedWordValidator` not `Validator2`
4. **Pre-instantiate validators** — Create instances outside the class definition for clarity

## Related

- [Basic Validators](./basic-validators.md) - Building individual validators
- [Regex Validators](./regex-validators.md) - Using RegexValidator in compositions
- [Parameterized Validators](./parameterized-validators.md) - Configurable validators for composition
