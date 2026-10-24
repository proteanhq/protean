# Command Inheritance

An abstract base command holds fields that several commands share, such as audit fields (`performed_by`) or a common `entity_id`. Concrete commands extend it and add their own fields.

## Code

The complete implementation is in [assets/command_inheritance.py](../assets/command_inheritance.py).

## Defining Abstract Commands

The examples on this page are commands for these two aggregates:

```python
@domain.aggregate
class Product:
    name: String(required=True, max_length=200)
    price: Float(required=True)

@domain.aggregate
class Customer:
    name: String(required=True, max_length=100)
    active: Boolean(default=True)
```

```python
@domain.command(abstract=True)
class AbstractEntityCommand:
    """Abstract base - defines common fields."""
    entity_id: Identifier(required=True)
    reason: String(max_length=500)
```

## Extending Abstract Commands

```python
@domain.command(part_of="Product")
class CreateProduct(AbstractEntityCommand):
    """Inherits entity_id and reason, adds own fields."""
    name: String(required=True, max_length=200)
    price: Float(required=True)
    category: String(max_length=100)
```

The concrete `CreateProduct` command has fields: `entity_id`, `reason`, `name`, `price`, `category`.

## Multi-Level Inheritance

```python
@domain.command(abstract=True)
class AbstractAuditedCommand:
    performed_by: String(required=True, max_length=100)

@domain.command(abstract=True)
class AbstractCustomerCommand(AbstractAuditedCommand):
    customer_id: Identifier(required=True)

@domain.command(part_of="Customer")
class DeactivateCustomer(AbstractCustomerCommand):
    deactivation_reason: String(required=True, max_length=500)
```

`DeactivateCustomer` has fields: `performed_by`, `customer_id`, `deactivation_reason`.

## When to Use Inheritance

Use a base command when many commands share the same fields, such as audit info. When only one or two commands would share it, repeat the fields instead.

## Inheritance Rules

1. Abstract commands use `abstract=True` in the decorator
2. Abstract commands do NOT specify `part_of`
3. Concrete commands MUST specify `part_of`
4. Fields are inherited from all ancestors
5. Concrete commands can override inherited field definitions
6. Abstract commands are never submitted. Protean lets you build an instance, but it has no aggregate, so `domain.process()` fails on it. Submit a concrete subclass.

## Related

- [Command Validation](./command-validation.md): Inherited fields are validated too
- [Anti-patterns](./anti-patterns.md): Over-engineering inheritance hierarchies
