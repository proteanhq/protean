# Same-Aggregate Event Flow

An event handler that belongs to and processes events from the same aggregate. Use this pattern when the side effect targets the aggregate that raised the event.

## Overview

The same-aggregate event flow is the simplest event pattern:
1. An aggregate method changes state and raises an event
2. An event handler on the same aggregate reacts and performs a follow-up action
3. Both the aggregate and handler operate on the same stream

Common use cases:
- Generating derived data (confirmation numbers, tracking codes)
- Updating computed fields after state changes
- Triggering internal lifecycle transitions

## Code

The complete implementation is in [assets/add_event_same_aggregate.py](../assets/add_event_same_aggregate.py).

Key highlights:
- Event is defined with `part_of="Order"` (string reference to aggregate)
- Aggregate method `place()` guards against invalid transitions, then raises the event
- Event handler uses `part_of=Order` (class reference) with no `stream_category` — defaults to its own stream
- Handler loads the aggregate from repository, mutates, and persists

## Walkthrough

### The Event

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
```

- Named in past-tense (`OrderPlaced`, not `PlaceOrder`)
- `part_of` uses a **string** (not class reference)
- Carries only the data the handler needs

### The Aggregate Method

```python
def place(self):
    if self.status != "draft":
        raise ValueError(f"Cannot place order in '{self.status}' status")
    self.status = "placed"
    self.raise_(OrderPlaced(
        order_id=self.order_id,
        customer_id=self.customer_id,
        total_amount=self.total_amount,
    ))
```

- Business logic (guards) execute first
- State change happens before `self.raise_()`
- Event is raised at the end, after all validations pass

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

- `part_of=Order` (class reference) — handler belongs to Order aggregate
- No `stream_category` specified — defaults to Order's own stream
- Does NOT return a value (fire-and-forget)
- Runs within an implicit UnitOfWork

## When to use same-aggregate handlers

Use this pattern when:
- The side effect modifies the same aggregate that raised the event
- You need to generate derived data from the event
- The reaction is internal to the aggregate's lifecycle

**Not suitable when:**
- The side effect targets a different aggregate (use [cross-aggregate flow](./cross-aggregate-flow.md))
- You need to return a result to the caller (event handlers are fire-and-forget)

## Testing

When testing same-aggregate event flows:
1. Verify event is raised when aggregate method is called (check `aggregate._events`)
2. Verify handler processes the event correctly (check side effect on aggregate)
3. Test with synchronous processing (`domain.config["event_processing"] = "sync"`)

## Related
- [Cross-aggregate event flow](./cross-aggregate-flow.md) - Event triggers side effect in another aggregate
- [Multiple events flow](./multiple-events-flow.md) - Multiple events from one aggregate
- [event skill](../../event/SKILL.md) - Detailed event definition reference
- [event-handler skill](../../event-handler/SKILL.md) - Detailed handler reference
