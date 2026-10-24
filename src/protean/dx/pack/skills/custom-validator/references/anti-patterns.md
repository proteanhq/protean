# Custom Validator Anti-Patterns

## Raising `ValueError` instead of `ValidationError`

Protean's validation pipeline expects `ValidationError`, and it reports it under
the field name on every field type. Other exceptions behave differently by
field. On a basic field such as `String`, Pydantic catches a `ValueError` and
reports it under the field name. On a `ValueObject` field, a `ValueError` is
reported under `_entity`, away from the field. Any other exception type, such
as `TypeError`, propagates unhandled.

```python
# fragment
# WRONG
class PhoneValidator:
    def __call__(self, value):
        if not value.startswith("+"):
            raise ValueError("Invalid phone")  # scoped differently by field type
```

```python
# RIGHT
from protean.exceptions import ValidationError

class PhoneValidator:
    def __call__(self, value):
        if not value.startswith("+"):
            raise ValidationError("Invalid phone")  # -> {field: ["Invalid phone"]}
```

## Cross-field rules in a single-field validator

A validator receives one field's value. It cannot see sibling fields, so it
cannot express rules that span fields.

```python
# fragment
# WRONG: a validator can't reach end_date
class AfterStartValidator:
    def __call__(self, value):  # only gets one value
        if value < self.start:  # self.start isn't the sibling field
            raise ValidationError("end must be after start")
```

Instead, use an aggregate/value-object invariant for cross-field rules:

```python
@invariant.post
def end_after_start(self):
    if self.end_date <= self.start_date:
        raise ValidationError({"end_date": ["must be after start_date"]})
```

## Re-implementing built-in constraints

Length and range checks already exist as field parameters. A validator that
duplicates them adds nothing.

```python
# fragment
# WRONG
class MaxLenValidator:
    def __call__(self, value):
        if len(value) > 50:
            raise ValidationError("too long")
```

```python
# RIGHT: use the field parameter
name: String(max_length=50)
```

Reserve validators for what the built-ins can't express (formats, patterns,
domain rules).

## Hardcoded, non-reusable validators

A validator with baked-in constants only works in one place.

```python
# fragment
# WRONG: only ever validates these domains
class EmailDomainValidator:
    def __call__(self, value):
        if value.split("@")[-1] not in ("acme.com",):
            raise ValidationError("bad domain")
```

```python
# RIGHT: configurable, reusable across fields
class AllowedDomainValidator:
    def __init__(self, allowed):
        self.allowed = allowed
    def __call__(self, value):
        if value.split("@")[-1].lower() not in self.allowed:
            raise ValidationError("bad domain")
```

## Doing I/O inside a validator

Validators run on every assignment. A database/network call here makes every
write slow and couples the domain to infrastructure.

```python
# fragment
# WRONG: DB lookup on every set
class UniqueEmailValidator:
    def __call__(self, value):
        if current_domain.repository_for(User).find_by(email=value):  # NO
            raise ValidationError("email taken")
```

Uniqueness and other stateful checks belong in a handler/service before persist,
not in a field validator.
