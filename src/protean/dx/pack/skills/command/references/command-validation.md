# Command Validation

Commands validate their data on instantiation. Invalid data raises `InvalidDataError` with detailed error messages. This ensures that only valid commands reach command handlers.

## Overview

Protean commands validate data at creation time, not when processed. This "fail fast" approach catches errors early and provides clear feedback. Validation is automatic based on field definitions.

## Code

The complete implementation is in [assets/command_validation.py](../assets/command_validation.py).

Key highlights:
- Required fields must be provided
- String fields validate `max_length`
- Numeric fields validate `min_value` / `max_value`
- Unknown fields are rejected
- Default values fill in optional fields

## Field Validation Types

### Required Fields

Fields marked `required=True` must be provided:

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True)
    nickname: String()  # Optional - defaults to None

# OK
RegisterUser(user_id="USER-001", email="alice@example.com")

# Fails: missing required email
RegisterUser(user_id="USER-001")  # Raises InvalidDataError
```

### String max_length

```python
@domain.command(part_of="User")
class RegisterUser:
    username: String(required=True, max_length=50)

# OK
RegisterUser(username="alice_smith")

# Fails: exceeds max_length
RegisterUser(username="a" * 51)  # Raises InvalidDataError
```

### Numeric min_value / max_value

```python
@domain.command(part_of="Product")
class UpdatePricing:
    product_id: Identifier(required=True)
    new_price: Float(required=True, min_value=0.01)
    discount: Float(min_value=0.0, max_value=100.0)
```

### Default Values

Fields with defaults are optional:

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True)
    age: Integer(default=21)

cmd = RegisterUser(user_id="USER-001", email="a@b.com")
assert cmd.age == 21  # Default applied
```

## Unknown Field Rejection

Commands reject fields that are not defined in the class:

```python
@domain.command(part_of="User")
class RegisterUser:
    email: String(required=True)

# Raises InvalidDataError: {"foo": ["is invalid"]}
RegisterUser(email="alice@example.com", foo="bar")
```

## Error Message Format

`InvalidDataError` contains a `messages` dict mapping field names to error lists:

```python
try:
    RegisterUser(
        user_id="USER-001",
        email="alice@example.com",
        username="x" * 51,  # exceeds max_length=50
        password="secret",
    )
except InvalidDataError as e:
    print(e.messages)
    # {"username": ["value has more than 50 characters"]}
```

## Validation Best Practices

1. **Mark essential fields as required** - Commands should always carry complete intent
2. **Set appropriate max_length** - Prevent unbounded string input
3. **Use min_value/max_value for numerics** - Enforce business constraints at the boundary
4. **Use defaults sparingly** - Only for truly optional fields with sensible defaults
5. **Validate at command level, not handler** - Fail fast before processing begins

## Related

- [Commands with Value Objects](./with-value-objects.md) - Value object validation
- [Anti-patterns](./anti-patterns.md) - Common validation mistakes
