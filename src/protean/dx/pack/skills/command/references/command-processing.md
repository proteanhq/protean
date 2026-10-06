# Command Processing

Commands in Protean can be processed either synchronously or asynchronously. This reference covers the command submission workflow, processing modes, and how commands flow through the system.

## Overview

The command processing workflow is:
1. **Construct** - Create a command instance with required data
2. **Submit** - Call `domain.process(command)` to submit
3. **Dispatch** - Domain routes to the appropriate command handler
4. **Handle** - Command handler processes the command

## Code

The complete implementation is in [assets/submitting_commands.py](../assets/submitting_commands.py).

Key highlights:
- Commands are submitted via `domain.process()`
- Processing can be synchronous or asynchronous
- Domain automatically dispatches to the correct handler
- One command can only have one handler

## Submitting Commands

The examples on this page use this aggregate, command and command handler:

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="DRAFT")

    def place(self, total_amount):
        self.total_amount = total_amount
        self.status = "PLACED"

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.command_handler(part_of="Order")
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)
        domain.repository_for(Order).add(order)
```

Register the handler before `domain.init()`. A handler registered after `init()` is not wired to its command, and `domain.process()` then runs no handler and saves nothing.

Initialize the domain, then build and submit the command inside a domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    # Construct the command
    command = PlaceOrder(
        order_id="ORD-001",
        customer_id="CUST-123",
        total_amount=99.99,
    )

    # Submit to domain (uses domain config default)
    domain.process(command)
```

## Processing Modes

### Synchronous Processing

Command processed immediately, execution blocked until done:

```python
with domain.domain_context():
    # Per-instance override
    domain.process(command, asynchronous=False)
```

Use synchronous when:
- You need immediate feedback from command execution
- You want to ensure the command was processed before continuing
- The operation is part of a transaction that must complete atomically

### Asynchronous Processing

Command stored in event store, processed by background worker later:

```python
with domain.domain_context():
    # Per-instance override
    domain.process(command, asynchronous=True)
```

Use asynchronous when:
- You want to improve UI responsiveness
- Command processing might take a long time
- You want to distribute load across background workers
- Implementing CQRS with event sourcing patterns

### Domain-Wide Configuration

Set default processing mode for all commands:

```python
# In domain.toml
# command_processing = "sync"  # or "async"

# In code
domain.config["command_processing"] = "sync"
```

Default is `async` in domain configuration.

## Synchronous Command Flow

```
API Controller --> Domain: command (asynchronous=False)
Domain --> Event Store: Store command
Domain --> Command Handler: Process immediately
Command Handler --> Domain: Return result
Domain --> API Controller: Return result
```

## Asynchronous Command Flow

```
API Controller --> Domain: command (asynchronous=True)
Domain --> Event Store: Store with asynchronous=True
Domain --> API Controller: Acknowledge receipt (return immediately)

Later, asynchronously...
Protean Server --> Event Store: Poll for unprocessed commands
Event Store --> Protean Server: Return command
Protean Server --> Command Handler: Process command
```

## Command Handler Association

Commands are routed to handlers via the `@handle` decorator. `OrderCommandHandler` in the first block on this page routes `PlaceOrder` to `handle_place_order`.

Key rule: **One command, one handler**. A command can only be processed by a single command handler. This is different from events, which can have multiple handlers.

## Command Metadata

Commands automatically receive metadata:

- **Timestamp** - When the command was created
- **Unique ID** - Set in the headers when the command is processed
- **Type** - Domain name, class name and version, such as `Shop.PlaceOrder.v1`
- **Version** - Schema version from `__version__`
- **Domain metadata** - Processing flags (synchronous/asynchronous)

## Best Practices

1. **Use synchronous for critical paths** - Where immediate feedback is required
2. **Use asynchronous for fire-and-forget** - When responsiveness matters more than confirmation
3. **Keep handlers focused** - One handler method per command
4. **Handle failures gracefully** - Command handlers should validate and raise clear errors
5. **Use the Protean server for async** - Run `protean server --domain path/to/domain.py`

## Related

- [Command Validation](./command-validation.md) - Validation happens before processing
- [Command Inheritance](./command-inheritance.md) - Abstract commands
- `command-handler` - Detailed handler patterns
