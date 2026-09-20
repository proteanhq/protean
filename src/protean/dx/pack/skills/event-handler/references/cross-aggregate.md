# Cross-Aggregate Event Handling

An event handler that belongs to one aggregate but listens to events from a different aggregate's stream. This is the primary mechanism for inter-aggregate coordination in DDD.

## Overview

When an event handler specifies both `part_of` and `stream_category`, it belongs to the first aggregate but listens to the stream of the second. This enables eventual consistency between aggregates without direct coupling.

The pattern:
1. Aggregate A raises an event on its stream
2. Event handler (belonging to Aggregate B) listens to Aggregate A's stream
3. Handler loads Aggregate B, applies changes, and persists

## Code

The complete implementation is in [assets/event_handler_cross_aggregate.py](../assets/event_handler_cross_aggregate.py).

Key highlights:
- `@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)` -- belongs to Inventory, listens to Order stream
- Handler updates Inventory aggregate in response to Order events
- No coupling between Order and Inventory aggregates

## Walkthrough

### The Stream Category

```python
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    ...
```

- `part_of=Inventory` -- this handler belongs to the Inventory aggregate
- `stream_category=Order.meta_.stream_category` -- this handler listens to the Order aggregate's event stream

The `stream_category` should be set using `Aggregate.meta_.stream_category` to get the fully-qualified stream name. This ensures proper event routing. When an Order aggregate raises events, they are published to the Order stream, and ManageInventory picks them up.

### The Handler Method

```python
@handle(OrderShipped)
def reduce_stock_level(self, event: OrderShipped):
    repo = domain.repository_for(Inventory)
    inventory = repo._dao.find_by(book_id=event.book_id)
    inventory.in_stock -= event.quantity
    repo.add(inventory)
```

The handler:
1. Receives the `OrderShipped` event from the Order stream
2. Looks up the Inventory record by `book_id` using the DAO
3. Reduces the stock quantity
4. Persists the updated Inventory

### Why _dao.find_by?

In the cross-aggregate pattern, you often need to look up an aggregate by a non-identity field (e.g., `book_id` instead of the Inventory's primary key). The `_dao.find_by()` method allows querying by any field.

Alternatively, if you know the aggregate's identity, use `repo.get(id)`.

## Multiple Event Handlers for Same Event

Unlike commands (one handler per command), multiple event handlers can react to the same event:

```python
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    @handle(OrderPlaced)
    def reserve_stock(self, event): ...

@domain.event_handler(part_of=Notification, stream_category=Order.meta_.stream_category)
class OrderNotifier:
    @handle(OrderPlaced)
    def send_confirmation(self, event): ...
```

Both handlers process `OrderPlaced` independently. This enables fan-out patterns.

## Eventual Consistency

Cross-aggregate event handling provides eventual consistency. The Order aggregate's transaction completes first, then (asynchronously in production) the Inventory aggregate is updated. There is a brief window where the two aggregates are inconsistent, which is acceptable in most business scenarios.

## Related

- [Same-Aggregate](./same-aggregate.md) - Handling events from the same aggregate
- [Anti-patterns](./anti-patterns.md) - Common mistakes
- `event` - Events are the input to event handlers
- `aggregate` - Event handlers are always connected to aggregates
- `patterns/event-sourcing` - Event handlers in event sourcing context
