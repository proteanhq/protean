# Projection Field Type Restrictions

## Overview

Projections are restricted to basic field types only. References, Associations (HasOne, HasMany), and ValueObjects are not supported. This is a deliberate design decision rooted in the CQRS pattern and the purpose of projections as denormalized, flattened read models.

## Why only basic field types?

1. **Denormalization**: Projections are designed to avoid joins and complex queries. Flattened data is faster to read.
2. **Independence**: Projections should not depend on other domain elements at query time.
3. **Simplicity**: Read models should be simple data containers, not complex object graphs.
4. **Storage flexibility**: Basic types map cleanly to database columns and cache entries.
5. **Rebuild capability**: Projections can be rebuilt from events without needing relational integrity.

## Allowed field types

| Type | Example |
|------|---------|
| `Identifier` | `user_id: Identifier(identifier=True)` |
| `Auto` | `id: Auto(identifier=True)` |
| `String` | `name: String(max_length=100)` |
| `Text` | `description: Text()` |
| `Integer` | `count: Integer(default=0)` |
| `Float` | `price: Float(required=True)` |
| `Boolean` | `active: Boolean(default=True)` |
| `DateTime` | `created_at: DateTime()` |
| `Date` | `birth_date: Date()` |

## Disallowed field types

### ValueObject fields

```python
# This raises IncorrectUsageError at class definition time
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)
    email = ValueObject(Email)  # NOT ALLOWED
```

Error: `"Projections can only contain basic field types. Remove email (ValueObject) from class UserView"`

### Reference fields

```python
# This raises IncorrectUsageError at class definition time
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)
    role = Reference(Role)  # NOT ALLOWED
```

Error: `"Projections can only contain basic field types. Remove role (Reference) from class UserView"`

### Association fields

```python
# This raises IncorrectUsageError at class definition time
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)
    role = HasOne(Role)  # NOT ALLOWED
```

Error: `"Projections can only contain basic field types. Remove role (HasOne) from class UserView"`

## How to flatten complex data

Instead of complex field types, flatten nested data into basic fields:

### Before (aggregate with complex types)
```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer = Reference(Customer)
    items = HasMany(OrderItem)
    shipping_address = ValueObject(Address)
```

### After (projection with flattened fields)
```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer_name: String()
    customer_email: String()
    item_count: Integer()
    total_amount: Float()
    shipping_street: String()
    shipping_city: String()
    shipping_zip: String()
```

The projector is responsible for flattening the event data into the projection fields.

## Validation timing

Field type validation happens at **class definition time** (in `__init_subclass__`), not at registration time. This means the error is raised as soon as the class is defined, even before it's registered with the domain.

## Complete example

See [projection_field_validation.py](../assets/projection_field_validation.py) for a complete, runnable example demonstrating field type restrictions.

## Related

- [Basic Projection](basic-projection.md) - Defining projections
- [Anti-patterns](anti-patterns.md) - Common mistakes
