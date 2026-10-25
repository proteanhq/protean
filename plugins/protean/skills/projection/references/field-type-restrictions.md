# Projection Field Type Restrictions

## Why no References or Associations?

A projection is read without joins and must not depend on other domain elements at query time. It is rebuilt from events, so it needs no relational integrity. Basic types and value objects (stored as flattened shadow columns) map directly to database columns and cache entries.

## Allowed field types

SKILL.md's "Supported field types" section lists them.

## Disallowed field types

### Reference fields

```python
# fragment
# This raises IncorrectUsageError at class definition time
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)
    role = Reference(Role)  # NOT ALLOWED
```

Error: `"Projections can only contain basic field types and ValueObjects. Remove role (Reference) from class UserView"`

### Association fields

```python
# fragment
# This raises IncorrectUsageError at class definition time
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)
    role = HasOne(Role)  # NOT ALLOWED
```

Error: `"Projections can only contain basic field types and ValueObjects. Remove role (HasOne) from class UserView"`

## How to flatten complex data

### Before (aggregate with complex types)
```python
@domain.aggregate
class Customer:
    name: String()
    email: String()


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier()
    price: Decimal(precision=19, scale=4)


@domain.value_object
class Address:
    street: String()
    city: String()
    zip: String()


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
    total_amount: Decimal(precision=19, scale=4)
    shipping_street: String()
    shipping_city: String()
    shipping_zip: String()
```

The projector is responsible for flattening the event data into the projection fields.

The address could also stay a value object in the projection, because projections accept `ValueObject` fields:

```python
@domain.projection
class OrderShippingView:
    order_id: Identifier(identifier=True)
    shipping_address = ValueObject(Address)
```

## Validation timing

Field types are checked at **class definition time**, in `__init_subclass__`. A `BaseProjection` subclass with a `Reference` raises as soon as the class body runs, before any registration with the domain.

## Complete example

See [projection_field_validation.py](../assets/projection_field_validation.py) for a complete, runnable example demonstrating field type restrictions.

## Related

- [Basic Projection](basic-projection.md): Defining projections
- [Anti-patterns](anti-patterns.md): Common mistakes
