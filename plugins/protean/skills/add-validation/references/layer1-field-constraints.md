# Layer 1: Field Constraints

The simplest and most common validation layer. Field constraints validate individual field values automatically on assignment.

## Code

The complete implementation is in [assets/validation_layer1_field_constraints.py](../assets/validation_layer1_field_constraints.py).

## Available Constraints

### All fields

| Parameter | Type | Description |
|-----------|------|-------------|
| `required` | bool | Field must have a value (not None, "", [], etc.) |
| `default` | any/callable | Default value when not provided |
| `choices` | Enum/list | Value must be one of the specified options |
| `validators` | list | Custom validator callables (see [custom-validator](../../custom-validator/SKILL.md)) |

### String / Text fields

| Parameter | Type | Description |
|-----------|------|-------------|
| `max_length` | int | Maximum character count (default 255 for String) |
| `min_length` | int | Minimum character count |
| `sanitize` | bool | Strip unsafe HTML (default True for String) |

### Integer / Float fields

| Parameter | Type | Description |
|-----------|------|-------------|
| `min_value` | number | Minimum allowed value |
| `max_value` | number | Maximum allowed value |

### Identity fields

| Parameter | Type | Description |
|-----------|------|-------------|
| `identifier` | bool | Marks field as entity's unique ID (auto sets `required=True`, `unique=True`) |
| `unique` | bool | Value must be unique across all instances |

## When to Use Layer 1

- Type safety: "this must be a number" → `Integer()`
- Presence: "this is required" → `required=True`
- Bounds: "age must be 18-120" → `Integer(min_value=18, max_value=120)`
- Format: "must be a valid email" → `validators=[EmailValidator()]`
- Enum: "status must be draft/active/closed" → `choices=StatusEnum`

## When NOT to Use Layer 1

- Cross-field rules ("end > start") → Use Layer 2 or 3 invariants
- Context-dependent rules ("only admins can...") → Use Layer 4 guards
- Rules that depend on aggregate state → Use Layer 3 invariants

## Validation Timing

Field constraints validate immediately when a value is assigned:
1. During `__init__` (object creation)
2. During `__setattr__` (attribute assignment)

Errors are raised as `ValidationError` with field-to-messages dict.

## Related

- [custom-validator](../../custom-validator/SKILL.md) - Custom validators for `validators=[]`
- [Layer 2](./layer2-value-object-invariants.md) - VO invariants for concept rules
