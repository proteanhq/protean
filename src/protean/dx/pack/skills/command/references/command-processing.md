# Command Processing

You submit a command with `domain.process(command)`, and the domain routes it to its one command handler, synchronously or asynchronously.

## Code

The complete implementation is in [assets/submitting_commands.py](../assets/submitting_commands.py).

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

The handler runs at once, and `domain.process()` returns when it is done:

```python
with domain.domain_context():
    # Per-instance override
    domain.process(command, asynchronous=False)
```

### Asynchronous Processing

The command is stored in the event store, and a background worker processes it later. Run the worker with `protean server --domain path/to/domain.py`:

```python
with domain.domain_context():
    # Per-instance override
    domain.process(command, asynchronous=True)
```

### Domain-Wide Configuration

`command_processing` in `domain.toml` (or `domain.config["command_processing"]`) sets the default mode for all commands, `"sync"` or `"async"`. The default is `async`.

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

Commands are routed to handlers via the `@handle` decorator. `OrderCommandHandler` in the first block on this page routes `PlaceOrder` to `handle_place_order`. A command has exactly one handler, while an event can have several.

## Command Metadata

Commands automatically receive metadata:

- **Timestamp**: When the command was created
- **Unique ID**: Set in the headers when the command is processed
- **Type**: Domain name, class name and version, such as `Shop.PlaceOrder.v1`
- **Version**: Schema version from `__version__`
- **Domain metadata**: Processing flags (synchronous/asynchronous)

## Related

- [Command Validation](./command-validation.md): Validation happens before processing
- [Command Inheritance](./command-inheritance.md): Abstract commands
- `command-handler`: Detailed handler patterns
