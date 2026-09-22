---
name: command-handler
description: Define a Protean command handler - a class responsible for receiving domain commands and orchestrating state changes in aggregates. Command handlers extract data from commands, load or create aggregates, invoke aggregate methods, and persist state changes. They are always associated with one aggregate via part_of and use the @handle decorator to process specific command types. Use when you need to process a command, handle a domain action, write a command handler, implement the handler for a command, connect a command to aggregate logic, or implement the write side of CQRS. Each handler method runs within an implicit UnitOfWork for transactional safety.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Command Handler

## Basic structure

```python
from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain()

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(default="draft")

    def place(self):
        self.status = "placed"

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order = Order(order_id=command.order_id)
        order.place()
        domain.repository_for(Order).add(order)
```

## Key rules

1. **part_of is required** - Handler must be associated with an aggregate: `@domain.command_handler(part_of=Order)`
2. **Commands must match the same aggregate** - Commands handled must have `part_of` pointing to the SAME aggregate as the handler
3. **One handler per command** - A command can only be processed by ONE handler (Protean enforces this)
4. **Use @handle decorator** - Each handler method is decorated with `@handle(CommandClass)`
5. **Handler methods take self and command** - Signature: `def method_name(self, command: CommandClass)`
6. **Implicit UnitOfWork** - Each handler method runs within a UnitOfWork context automatically (no manual wrapping needed)
7. **Persist one aggregate** - Handler should persist only one aggregate root per operation; use domain events for cross-aggregate coordination
8. **Import handle from protean** - `from protean import handle` (not from protean.core)
9. **part_of uses class reference** - Handler uses `part_of=AggregateClass`, while commands use `part_of="AggregateName"` (string). Define the aggregate before the handler so the class resolves; unlike commands, command handlers do **not** accept a string `part_of` (it raises at registration)

## Handler options

| Option | Purpose | Required |
|--------|---------|----------|
| `part_of` | Associate handler with an aggregate class | Yes |
| `stream_category` | Read-only, derived from aggregate | No |

## Quick example: Multiple commands

```python
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        account = Account(
            account_id=command.account_id,
            email=command.email,
        )
        domain.repository_for(Account).add(account)

    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        account = domain.repository_for(Account).get(command.account_id)
        account.activate()
        domain.repository_for(Account).add(account)
```

## Handler workflow

1. **Receive command** - Domain dispatches command to the matching handler method
2. **Load or create aggregate** - Use `domain.repository_for(Aggregate).get(id)` to load, or construct a new instance
3. **Extract data and invoke method** - Call aggregate methods with data from the command
4. **Persist** - Use `domain.repository_for(Aggregate).add(aggregate)` to save

## Processing commands

```python
# Synchronous - blocks until done, returns handler result
result = domain.process(command, asynchronous=False)

# Asynchronous (default) - returns position in event store
position = domain.process(command)
```

## Error handling

Override `handle_error` classmethod for custom error recovery during async processing:

```python
@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    @handle(TransferFunds)
    def handle_transfer(self, command):
        # ... handler logic ...
        pass

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        logger.error(f"Payment failed: {exc}")
```

## Common mistakes

### Missing part_of on handler

```python
@domain.command_handler  # Wrong! Missing part_of
class OrderCommandHandler:
    pass
```

Instead: Always specify part_of with the aggregate class

```python
@domain.command_handler(part_of=Order)  # Correct!
class OrderCommandHandler:
    pass
```

### Command associated with different aggregate

```python
@domain.command(part_of="Shipment")
class ShipOrder:
    order_id: Identifier(required=True)

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(ShipOrder)  # Wrong! ShipOrder is part_of Shipment, not Order
    def handle_ship(self, command):
        pass
```

Instead: Command and handler must share the same aggregate

### Handling the same command in multiple handlers

```python
@domain.command_handler(part_of=Order)
class OrderHandler1:
    @handle(PlaceOrder)  # First handler
    def handle(self, command):
        pass

@domain.command_handler(part_of=Order)
class OrderHandler2:
    @handle(PlaceOrder)  # Wrong! PlaceOrder already handled by OrderHandler1
    def handle(self, command):
        pass
```

### Wrapping in UnitOfWork manually

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Unnecessary! Already implicit
        order = Order(...)
        domain.repository_for(Order).add(order)
```

Instead: Let the implicit UnitOfWork handle it

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(...)
    domain.repository_for(Order).add(order)
```

## Detailed references

### Core Concepts
- [Loading Aggregates](references/loading-aggregates.md) - Hydrating aggregates from the repository
- [Unit of Work](references/unit-of-work.md) - Implicit transactional behavior
- [Error Handling](references/error-handling.md) - Custom error recovery with handle_error
- [Return Values](references/return-values.md) - Returning data from handlers
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple Handler](assets/command_handler_simple.py) - Basic handler with one command
- [Multiple Commands](assets/command_handler_multiple_commands.py) - Handler with multiple @handle methods
- [Handler with Events](assets/command_handler_with_events.py) - Aggregate raises events during handling
- [Error Handling](assets/command_handler_error_handling.py) - Custom handle_error classmethod
- [Create Aggregate](assets/command_handler_create_aggregate.py) - Creating new aggregates vs. loading

### Related Skills
- `command` - Commands are the input to command handlers
- `aggregate` - Command handlers operate on aggregates
- `event` - Aggregates may raise events during handler processing
- `event-handler` - Downstream processing of events raised during command handling

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
