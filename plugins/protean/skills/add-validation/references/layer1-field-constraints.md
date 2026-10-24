# Layer 1: Field Constraints

Field constraints validate each field's value when it is assigned, in `__init__` and in `__setattr__`. A failure raises `ValidationError` with a dict of field name to messages.

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
| `sanitize` | bool | Clean unsafe HTML with `bleach.clean()`: it escapes disallowed tags and removes disallowed attributes and HTML comments (default: off; set `True` per field, or domain-wide via `[field_defaults] sanitize`) |

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

## Related

- [custom-validator](../../custom-validator/SKILL.md): Custom validators for `validators=[]`
- [Layer 2](./layer2-value-object-invariants.md): VO invariants for concept rules
