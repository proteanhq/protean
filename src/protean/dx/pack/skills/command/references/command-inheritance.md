# Command Inheritance

Commands support inheritance through abstract base commands. This enables sharing common fields across related commands while keeping each command focused.

## Overview

Abstract commands define shared fields and behavior. Concrete commands extend them and add their own fields. This is useful for:

- **Shared audit fields** - `performed_by`, `timestamp` across all commands
- **Shared entity identifiers** - Common `entity_id` field
- **Domain-specific base commands** - Group related commands under a common base

## Code

The complete implementation is in [assets/command_inheritance.py](../assets/command_inheritance.py).

Key highlights:
- Abstract commands use `@domain.command(abstract=True)`
- Abstract commands do NOT require `part_of` (they are never instantiated)
- Concrete commands inherit all parent fields
- Multi-level inheritance is supported

## Defining Abstract Commands

```python
@domain.command(abstract=True)
class AbstractEntityCommand:
    """Abstract base - defines common fields."""
    entity_id: Identifier(required=True)
    reason: String(max_length=500)
```

Abstract commands:
- Cannot be instantiated directly
- Do not require `part_of` parameter
- Define fields that all child commands inherit

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

Commands can form deeper hierarchies:

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

Use command inheritance when:
- Multiple commands share the same fields (e.g., audit info)
- You want to enforce that all commands in a domain area have certain fields
- You are building a consistent command vocabulary for a bounded context

Avoid when:
- Commands have no meaningful shared structure
- Only one or two commands would share the base (just duplicate the fields)

## Inheritance Rules

1. Abstract commands use `abstract=True` in the decorator
2. Abstract commands do NOT specify `part_of`
3. Concrete commands MUST specify `part_of`
4. Fields are inherited from all ancestors
5. Concrete commands can override inherited field definitions
6. Abstract commands cannot be instantiated

## Related

- [Command Validation](./command-validation.md) - Inherited fields are validated too
- [Anti-patterns](./anti-patterns.md) - Over-engineering inheritance hierarchies
