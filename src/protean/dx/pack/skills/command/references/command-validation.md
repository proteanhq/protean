# Command Validation

Commands validate their data on instantiation. Invalid data raises `protean.exceptions.ValidationError` with an error message for each failing field. This ensures that only valid commands reach command handlers.

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

The examples on this page are commands for these aggregates. Each example catches `ValidationError` from `protean.exceptions`:

```python
from protean.exceptions import ValidationError

@domain.aggregate
class User:
    email: String(required=True)

@domain.aggregate
class Product:
    name: String(required=True)
```

A command checks its data when you build it, so each example initializes the domain and builds commands inside a domain context.

### Required Fields

Fields marked `required=True` must be provided:

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True)
    nickname: String()  # Optional - defaults to None

domain.init(traverse=False)

with domain.domain_context():
    # OK
    RegisterUser(user_id="USER-001", email="alice@example.com")

    # Fails: missing required email
    try:
        RegisterUser(user_id="USER-001")
    except ValidationError as e:
        print(e.messages)  # {'email': ['is required']}
```

### String max_length

```python
@domain.command(part_of="User")
class RegisterUser:
    username: String(required=True, max_length=50)

domain.init(traverse=False)

with domain.domain_context():
    # OK
    RegisterUser(username="alice_smith")

    # Fails: exceeds max_length
    try:
        RegisterUser(username="a" * 51)
    except ValidationError as e:
        print(e.messages)  # {'username': ['String should have at most 50 characters']}
```

### Numeric min_value / max_value

```python
@domain.command(part_of="Product")
class UpdatePricing:
    product_id: Identifier(required=True)
    new_price: Float(required=True, min_value=0.01)
    discount: Float(min_value=0.0, max_value=100.0)

domain.init(traverse=False)

with domain.domain_context():
    try:
        UpdatePricing(product_id="PROD-001", new_price=0.0)
    except ValidationError as e:
        print(e.messages)  # {'new_price': ['Input should be greater than or equal to 0.01']}
```

### Default Values

Fields with defaults are optional:

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True)
    age: Integer(default=21)

domain.init(traverse=False)

with domain.domain_context():
    cmd = RegisterUser(user_id="USER-001", email="a@b.com")
    assert cmd.age == 21  # Default applied
```

## Unknown Field Rejection

Commands reject fields that are not defined in the class:

```python
@domain.command(part_of="User")
class RegisterUser:
    email: String(required=True)

domain.init(traverse=False)

with domain.domain_context():
    try:
        RegisterUser(email="alice@example.com", foo="bar")
    except ValidationError as e:
        print(e.messages)  # {'foo': ['Extra inputs are not permitted']}
```

## Error Message Format

`ValidationError` has a `messages` dict. Each key is a field name, and each value is a list of error strings for that field. One error reports every field that failed:

```python
@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True, max_length=250)
    username: String(required=True, max_length=50)
    password: String(required=True, max_length=255)

domain.init(traverse=False)

with domain.domain_context():
    try:
        RegisterUser(
            user_id="USER-001",
            email="alice@example.com",
            username="x" * 51,  # exceeds max_length=50
            password="secret",
        )
    except ValidationError as e:
        print(e.messages)
        # {'username': ['String should have at most 50 characters']}

    try:
        RegisterUser(user_id="USER-001")
    except ValidationError as e:
        print(e.messages)
        # {'email': ['is required'], 'username': ['is required'], 'password': ['is required']}
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
