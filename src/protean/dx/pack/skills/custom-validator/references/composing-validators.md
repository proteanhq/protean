# Composing Validators

Chain multiple validators on a single field for layered validation.

## Overview

When a single field needs to satisfy multiple rules (format, business logic, deny-list), compose validators by passing a list to the `validators=[]` parameter. Validators run in list order, and validation stops at the first failing validator.

## Code

The complete implementation is in [assets/custom_validator_composition.py](../assets/custom_validator_composition.py).

Key highlights:
- Username validated by 4 different validators (format, reserved words, profanity, consecutive chars)
- Coupon code validated by format regex, then prefix check
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
1. Empty values (`None`, `""`, `[]`, `()`, `{}`) skip the validators entirely. Use `required=True` to reject a missing value.
2. Built-in constraints such as `max_length` and `min_value` run first. A value that fails one of them never reaches the custom validators.
3. Validators run in list order.
4. Validation stops at the first failing validator. Later validators do not run.
5. The field gets one `ValidationError` message. It is the validator's `error` attribute when the validator has one, and the message it raised otherwise.

**Important**: The user sees one error for the field at a time. A value that breaks several rules reports only the first rule it breaks. Once the user fixes that, the next rule in the list fails on the next attempt.

**`ValueObject` and `ValueObjectList` fields behave differently**: every validator in the list runs, and the field reports one error for each validator that failed.

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

## Only the First Failure Is Reported

`"spam__bot"` breaks two rules: it contains a blocked word, and it has two underscores in a row. The profanity validator comes first in the list, so only its error is raised:

```python
UserAccount(username="spam__bot", display_name="Spam Bot")
# ValidationError: {'username': ['Value contains prohibited content']}
```

The consecutive-characters validator never runs for this value.

## Best Practices

1. **Order decides which error the user sees** — Put the most basic or cheapest check first, such as the format check before a business rule.
2. **Keep each validator focused** — One rule per validator class
3. **Name validators clearly** — `ReservedWordValidator` not `Validator2`
4. **Pre-instantiate validators** — Create instances outside the class definition for clarity

## Related

- [Basic Validators](./basic-validators.md) - Building individual validators
- [Regex Validators](./regex-validators.md) - Using RegexValidator in compositions
- [Parameterized Validators](./parameterized-validators.md) - Configurable validators for composition
