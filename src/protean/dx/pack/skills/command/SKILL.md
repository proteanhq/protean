---
name: command
description: Define a Protean command - an immutable DTO representing an intent to change aggregate state. Commands encapsulate the data necessary to perform a specific action and are processed by command handlers. Commands are always associated with aggregates and are named with imperative verbs (PlaceOrder, RegisterUser, CancelReservation). Use when you need to define an action or operation that changes domain state, when the user asks to "create a command", "define a command", "add a command", when implementing CQRS patterns, or when they describe an action they want to perform (like "place an order", "register a user", "cancel a reservation"). Commands can be processed synchronously or asynchronously.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Command

## Basic structure

A command is defined using the `@domain.command(part_of="...")` decorator:

```python
from protean import Domain
from protean.fields import String, Identifier

domain = Domain()

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    product_id: String(required=True)
```

## Key rules

1. **Commands must be associated with aggregates** - Always specify `part_of` parameter with the aggregate name
2. **Commands are named with imperative verbs** - Use imperative mood: `PlaceOrder`, not `OrderPlaced`
3. **Commands are immutable** - Once created, commands cannot be modified
4. **Commands are DTOs** - Can contain simple fields and value objects, but NOT entities or aggregates (no HasOne, HasMany)
5. **Commands are unique** - Each command is unique throughout the domain
6. **One handler per command** - A command can only be processed by one command handler
7. **Commands carry intent** - They describe what should happen, not what happened (that is events)
8. **Commands have metadata** - Protean automatically adds timestamps, unique IDs, and versioning
9. **Commands are submitted via `domain.process()`** - The domain dispatches to the appropriate handler
10. **Commands support sync and async processing** - Controlled per-instance or via domain configuration

## Fields and options

| Field/Option | Purpose | Required |
|--------------|---------|----------|
| `part_of` | Associate command with an aggregate | Yes (unless abstract) |
| `abstract` | Mark as abstract base command | No |
| `__version__` | Schema version as positive integer (defaults to `1`) | No |

### Supported field types

```python
from protean.fields import (
    String, Integer, Float, Boolean,
    DateTime, Date, Identifier,
    List, Dict, ValueObject,
)
```

Commands cannot use `HasOne`, `HasMany`, or `Reference` fields.

## Quick example

```python
from protean import Domain
from protean.fields import String, Float, DateTime, Identifier

domain = Domain()

@domain.aggregate
class Order:
    order_id: Identifier(required=True)

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)

# Create and submit command
command = PlaceOrder(
    order_id="ORD-001",
    customer_id="CUST-123",
    total_amount=99.99
)
domain.process(command)
```

## Submitting commands

Commands are submitted to the domain for processing:

```python
# Default processing (based on domain config, default is async)
domain.process(command)

# Explicit synchronous processing
domain.process(command, asynchronous=False)

# Explicit asynchronous processing
domain.process(command, asynchronous=True)
```

Domain-wide configuration:

```python
# In domain.toml
# command_processing = "sync"  # or "async"

# In code
domain.config["command_processing"] = "sync"
```

## Common mistakes

### Using past-tense verbs instead of imperative

```python
@domain.command(part_of="Order")
class OrderPlaced:  # Wrong! This is an event name
    pass
```

Instead: Use imperative verbs

```python
@domain.command(part_of="Order")
class PlaceOrder:  # Correct! Imperative verb
    pass
```

### Not associating command with aggregate

```python
@domain.command  # Wrong! Missing part_of
class PlaceOrder:
    pass
```

Instead: Always specify part_of

```python
@domain.command(part_of="Order")  # Correct!
class PlaceOrder:
    pass
```

### Including entities in commands

```python
@domain.command(part_of="Order")
class PlaceOrder:
    items = HasMany(OrderItem)  # Wrong! Commands can't contain entities
```

Instead: Only fields and value objects

```python
@domain.command(part_of="Order")
class PlaceOrder:
    items: List()  # Serialize as list of dicts
    total = ValueObject(Money)  # Value objects are allowed
```

### Trying to modify a command after creation

```python
command = PlaceOrder(order_id="ORD-001", customer_id="CUST-123")
command.customer_id = "CUST-456"  # Raises IncorrectUsageError!
```

Instead: Create a new command instance

```python
command = PlaceOrder(order_id="ORD-001", customer_id="CUST-456")
```

## Detailed references

### Core Concepts
- [Commands with Value Objects](references/with-value-objects.md) - Using value objects in commands
- [Command Validation](references/command-validation.md) - Field validation and error handling
- [Command Processing](references/command-processing.md) - Synchronous and asynchronous processing
- [Command Inheritance](references/command-inheritance.md) - Abstract commands and inheritance
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple Command](assets/command_simple.py) - Basic commands with simple fields
- [Command with Value Objects](assets/command_with_value_object.py) - Commands containing value objects
- [Command Validation](assets/command_validation.py) - Field validation examples
- [Command Inheritance](assets/command_inheritance.py) - Abstract base commands and inheritance
- [Submitting Commands](assets/submitting_commands.py) - Command submission and processing

### Related Skills
- `aggregate` - Commands are always part of aggregates
- `command-handler` - How commands are processed
- `event` - Commands and events are complementary (commands = intent, events = result)
- `value-object` - Commands can contain value objects
- `patterns/cqrs` - Commands are the "C" in CQRS
