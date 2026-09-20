# Commands with Value Objects

Commands can contain value objects to represent complex immutable data structures. This enables commands to carry rich, structured intent while maintaining immutability and type safety.

## Overview

Value objects are immutable complex types that represent domain concepts with multiple attributes (Money, Address, Coordinates, etc.). Including value objects in commands provides:

- **Type safety** - Structured data with validation
- **Immutability** - Value objects are immutable, perfect for commands
- **Domain modeling** - Express domain concepts clearly
- **Reusability** - Same value objects used across commands, events, and aggregates

## Code

The complete implementation is in [assets/command_with_value_object.py](../assets/command_with_value_object.py).

Key highlights:
- Value objects encapsulate complex immutable data
- Commands use `ValueObject()` field to reference them
- Same value objects can be shared across commands, events, and aggregates
- Type safety and validation built-in

## Common Value Objects in Commands

### Money

The most common value object in business commands:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
```

### Address

For shipping, billing, and location updates:

```python
@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.command(part_of="Customer")
class UpdateCustomerAddress:
    customer_id: Identifier(required=True)
    new_address = ValueObject(Address, required=True)
```

## Multiple Value Objects in One Command

Commands can contain multiple value objects:

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)

    # Multiple value objects
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)  # Optional
```

## Value Objects vs Simple Fields

### When to Use Value Objects

Use value objects when:
- Multiple related attributes form a cohesive concept (Money has amount + currency)
- You need behavior/validation on the data (currency conversion, address validation)
- The concept is reused across multiple commands/events/aggregates
- Type safety and domain clarity are important

### When to Use Simple Fields

Use simple fields when:
- Single primitive value is sufficient
- No related attributes or behavior needed
- Concept is specific to this one command

```python
# Good: Simple field for single value
@domain.command(part_of="User")
class ChangeUserEmail:
    user_id: Identifier(required=True)
    new_email: String(required=True)  # Just a string

# Good: Value object for complex concept
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    total = ValueObject(Money, required=True)  # Complex: amount + currency
```

## Best Practices

1. **Reuse value objects** - Same value objects across commands, events, and aggregates
2. **Keep value objects immutable** - Never add methods that modify state
3. **Add behavior to value objects** - Validation, calculations, formatting
4. **Use composition** - Value objects can contain other value objects
5. **Document purpose** - Clear docstrings on value objects and their usage

## Related

- [Command Validation](./command-validation.md) - Validation on command fields
- [Anti-patterns](./anti-patterns.md) - Common mistakes
- `value-object` - Detailed value object patterns
