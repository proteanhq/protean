# Same-Aggregate Event Handling

An event handler that belongs to the same aggregate whose events it processes. This is the simplest event handler pattern.

## Overview

When an event handler's `part_of` points to an aggregate and no `stream_category` is specified, the handler automatically listens to that aggregate's own event stream. Use this when the aggregate needs reactive side effects triggered by its own state changes.

Common use cases:
- Generating confirmation numbers or reference codes after an action
- Updating derived state within the same aggregate boundary
- Triggering internal workflows (e.g., scheduling follow-ups)

## Code

The complete implementation is in [assets/event_handler_same_aggregate.py](../assets/event_handler_same_aggregate.py).

Key highlights:
- `@domain.event_handler(part_of=Order)` -- handler belongs to Order, listens to Order stream
- No `stream_category` needed -- defaults to the aggregate's own stream
- Handler loads the aggregate from the repository, mutates it, and persists

## Walkthrough

### The Event

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
```

The event is a simple DTO containing the data needed by downstream handlers.

### The Aggregate

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    confirmation_number: String()

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(...))
```

The aggregate raises the event inside its business method via `self.raise_()`.

### The Event Handler

```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        repo.add(order)
```

The handler loads the aggregate from the repository (it gets a fresh copy, not the same instance that raised the event), applies side effects, and persists.

## When to Use Same-Aggregate Handlers

- Side effects that belong conceptually to the same aggregate
- Updating derived or computed state after a domain action
- When no cross-aggregate coordination is needed

## When NOT to Use

- If the handler updates a different aggregate, use a cross-aggregate handler instead
- If the logic is part of the core business rule, keep it in the aggregate method itself

## Related

- [Cross-Aggregate](./cross-aggregate.md) - Handling events from another aggregate
- [Anti-patterns](./anti-patterns.md) - Common mistakes
- `event` - Events are the input to event handlers
- `aggregate` - Event handlers are always connected to aggregates
