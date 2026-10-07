# Cross-Aggregate Event Handling

An event handler that reacts to one aggregate's event and changes a different aggregate. This is the primary mechanism for inter-aggregate coordination in DDD.

## Overview

The handler sits in the cluster that owns the event. It does not write the other aggregate itself. It issues a command that belongs to the other aggregate, and that aggregate's command handler does the write. Each aggregate changes in its own transaction.

The pattern:
1. Aggregate A raises an event on its stream
2. An event handler in A's cluster (`part_of=A`, no `stream_category`) reacts to the event
3. The handler calls `current_domain.process(...)` with a command that belongs to Aggregate B
4. B's command handler loads B, applies the change, and persists

For a flow with several causally dependent steps, where each step waits on the outcome of the one before, use a process manager. See [process-manager](../../process-manager/SKILL.md).

## Code

The complete implementation is in [assets/event_handler_cross_aggregate.py](../assets/event_handler_cross_aggregate.py).

Key highlights:
- `@domain.event_handler(part_of=Order)`: the handler sits in Order's cluster, which owns `OrderShipped`
- The handler issues a `ReduceStock` command, which belongs to Inventory
- Inventory's command handler reduces the stock and skips an order it has already applied

## Walkthrough

### The Event Handler

```python
@domain.event_handler(part_of=Order)
class ManageInventory:
    @handle(OrderShipped)
    def reduce_stock_level(self, event: OrderShipped):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                book_id=event.book_id,
                quantity=event.quantity,
            )
        )
```

- `part_of=Order`: the handler belongs to the cluster that owns `OrderShipped`
- No `stream_category`: the handler listens to Order's own stream by default
- `current_domain.process(ReduceStock(...))`: the handler hands the change to Inventory

A handler with `part_of=Inventory` that reacts to `OrderShipped` couples the two clusters directly, and `check` reports it as `EVENT_HANDLER_FOREIGN_EVENT`. See [Anti-patterns](./anti-patterns.md).

### The Command

```python
@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
```

The command carries everything Inventory needs, so its handler does not load the Order. `order_id` is a deterministic id taken from the event.

### The Command Handler

```python
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(book_id=command.book_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied; reducing again would double count
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

The handler:
1. Looks up the Inventory record by `book_id` with `repo.find_by()`
2. Returns without changes if this order was already applied
3. Reduces the stock through the aggregate method, which also records the order id
4. Persists the updated Inventory

### Why the guard?

Events are delivered at least once, so `OrderShipped` can reach the handler twice and issue `ReduceStock` twice. Reducing stock is an update, so Inventory keeps `applied_order_ids: List(content_type=String)` and the command handler checks it before changing anything. When the command creates the target aggregate, check for an existing record instead:

```python
# fragment
try:
    repository.get(command.order_id)
except ObjectNotFoundError:
    repository.add(Shipment.start(command.order_id))
else:
    return  # already created
```

Never generate a fresh `uuid4()` in the event handler, because a redelivered event would then look like new work.

### Why find_by?

The command often carries a field that is not the target aggregate's identity (here `book_id`). The repository's `find_by()` method queries by any field and returns exactly one aggregate. It raises `ObjectNotFoundError` when nothing matches and `TooManyObjectsError` when more than one record does.

If you know the aggregate's identity, use `repo.get(id)`.

## Multiple Event Handlers for Same Event

Unlike commands (one handler per command), multiple event handlers can react to the same event. Each one sits in the cluster that owns the event and issues its own command:

```python
@domain.event_handler(part_of=Order)
class ManageInventory:
    @handle(OrderPlaced)
    def reserve_stock(self, event):
        current_domain.process(ReserveStock(order_id=event.order_id))

@domain.event_handler(part_of=Order)
class OrderNotifier:
    @handle(OrderPlaced)
    def send_confirmation(self, event):
        current_domain.process(SendConfirmation(order_id=event.order_id))
```

Both handlers process `OrderPlaced` independently. This enables fan-out patterns.

## Eventual Consistency

Cross-aggregate event handling provides eventual consistency. The Order aggregate's transaction completes first, then (asynchronously in production) the Inventory aggregate is updated. There is a brief window where the two aggregates are inconsistent, which is acceptable in most business scenarios.

## Related

- [Same-Aggregate](./same-aggregate.md) - Handling events from the same aggregate
- [Cross-Aggregate Patterns](./cross-aggregate-patterns.md) - Common sync scenarios
- [Anti-patterns](./anti-patterns.md) - Common mistakes
- `command-handler` - The write path the handler hands off to
- `process-manager` - Flows with several causally dependent steps
- `event` - Events are the input to event handlers
- `aggregate` - Event handlers are always connected to aggregates
- `event-sourced-aggregate` - Aggregates whose state is rebuilt from their events
