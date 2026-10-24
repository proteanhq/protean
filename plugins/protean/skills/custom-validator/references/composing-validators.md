# Composing Validators

When a single field needs to satisfy multiple rules (format, business logic, deny-list), compose validators by passing a list to the `validators=[]` parameter. Validators run in list order, and validation stops at the first failing validator.

## Code

The complete implementation is in [assets/custom_validator_composition.py](../assets/custom_validator_composition.py).

## How Composition Works

The username field uses four validators: a format regex and three custom
classes. Define them first:

```python
from protean.exceptions import ValidationError
from protean.fields.validators import RegexValidator


class ReservedWordValidator:
    def __init__(self, reserved_words):
        self.reserved_words = [w.lower() for w in reserved_words]

    def __call__(self, value):
        if value.lower() in self.reserved_words:
            raise ValidationError(f"'{value}' is reserved and cannot be used")


class NoProfanityValidator:
    def __init__(self, blocked_words):
        self.blocked_words = [w.lower() for w in blocked_words]

    def __call__(self, value):
        if any(word in value.lower() for word in self.blocked_words):
            raise ValidationError("Value contains prohibited content")


class NoConsecutiveSpecialCharsValidator:
    def __init__(self, special_chars="_-."):
        self.special_chars = special_chars

    def __call__(self, value):
        for current, following in zip(value, value[1:]):
            if current in self.special_chars and following in self.special_chars:
                raise ValidationError("Cannot contain consecutive special characters")


format_validator = RegexValidator(
    regex=r"^[a-zA-Z][a-zA-Z0-9_.-]{2,29}$",
    message="Username must start with a letter, 3-30 chars",
)
reserved_validator = ReservedWordValidator(["admin", "root", "system"])
profanity_validator = NoProfanityValidator(["spam", "hack"])
consecutive_validator = NoConsecutiveSpecialCharsValidator()
```

Then list them on the field in the order they should run:

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
    display_name: String(required=True, max_length=100)
```

**Execution order**:
1. Empty values (`None`, `""`, `[]`, `()`, `{}`) skip the validators entirely. Use `required=True` to reject a missing value.
2. Built-in constraints such as `max_length` and `min_value` run first. A value that fails one of them never reaches the custom validators.
3. Validators run in list order.
4. Validation stops at the first failing validator. Later validators do not run.
5. The field gets one `ValidationError` message. It is the validator's `error` attribute when the validator has one, and the message it raised otherwise.

The user sees one error for the field at a time. Once the user fixes that, the next rule in the list fails on the next attempt.

**`ValueObject` and `ValueObjectList` fields behave differently**: every validator in the list runs, and the field reports one error for each validator that failed.

## Combining RegexValidator with Custom Validators

`PrefixValidator` is a custom validator that checks a business rule: the code
must start with one of the allowed prefixes.

```python
class PrefixValidator:
    def __init__(self, prefixes):
        self.prefixes = prefixes
        self.error = f"Must start with one of: {', '.join(prefixes)}"

    def __call__(self, value):
        if not any(value.startswith(prefix) for prefix in self.prefixes):
            raise ValidationError(self.error)


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
domain.init(traverse=False)

with domain.domain_context():
    try:
        UserAccount(username="spam__bot", display_name="Spam Bot")
    except ValidationError as exc:
        assert exc.messages == {"username": ["Value contains prohibited content"]}
    else:
        raise AssertionError("spam__bot should be rejected")
```

The consecutive-characters validator never runs for this value.

## Best Practices

1. **Order decides which error the user sees**: Go from general to specific: format, then business rules, then content policy, then style rules. The cheapest check goes first.
2. **Keep each validator focused**: One rule per validator class

## Related

- [Basic Validators](./basic-validators.md): Building individual validators
- [Regex Validators](./regex-validators.md): Using RegexValidator in compositions
- [Parameterized Validators](./parameterized-validators.md): Configurable validators for composition
