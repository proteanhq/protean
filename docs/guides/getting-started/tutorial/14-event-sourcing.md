# Chapter 14: Event Sourcing

Throughout this tutorial, we have stored *current state* — when an order
is confirmed, we update its status in the database. With **event
sourcing**, we store *events* instead. The current state is reconstructed
by replaying those events. This gives you a complete audit trail and the
ability to answer "what happened and when?"

## What Is Event Sourcing?

In traditional persistence:

```
Order: {status: "CONFIRMED", customer: "Alice", ...}
```

The database holds the latest state. Previous states are lost.

With event sourcing:

```
1. OrderPlaced   {customer: "Alice", items: [...]}
2. OrderConfirmed {confirmed_at: "2024-01-15"}
3. OrderShipped   {tracking: "ABC123"}
```

The database holds the sequence of events. Current state is derived
by replaying them.

### When to Use Event Sourcing

| Use Event Sourcing When... | Use Traditional When... |
|---------------------------|----------------------|
| Audit trail is critical | State is simple |
| You need temporal queries | Performance is paramount |
| Domain has complex state transitions | Few state changes |
| Regulatory compliance requires history | Simplicity is preferred |

## Converting to Event-Sourced

To make an aggregate event-sourced, add `is_event_sourced=True`:

```python
@domain.aggregate(is_event_sourced=True)
class Order:
    customer_name = String(max_length=150, required=True)
    status = String(max_length=20, default="PENDING")
    items = HasMany("OrderItem")
    ...
```

With this flag, the aggregate is no longer persisted as a row. Instead,
its events are stored in an **event store**, and the aggregate is
reconstructed by replaying those events.

## The `@apply` Decorator

Event-sourced aggregates need methods that know how to apply each event
to the aggregate's state:

```python
from protean.core.aggregate import apply

@domain.aggregate(is_event_sourced=True)
class Order:
    customer_name = String(max_length=150, required=True)
    status = String(max_length=20, default="PENDING")

    @classmethod
    def place(cls, customer_name, items):
        order = cls(customer_name=customer_name)
        order.raise_(OrderPlaced(
            order_id=order.id,
            customer_name=customer_name,
        ))
        return order

    def confirm(self):
        self.raise_(OrderConfirmed(order_id=self.id))

    def ship(self):
        self.raise_(OrderShipped(order_id=self.id))

    @apply
    def when_placed(self, event: OrderPlaced):
        self.status = "PENDING"

    @apply
    def when_confirmed(self, event: OrderConfirmed):
        self.status = "CONFIRMED"

    @apply
    def when_shipped(self, event: OrderShipped):
        self.status = "SHIPPED"
```

Key points:

- **`@apply`** methods are called when events are replayed. Each method
  handles one event type based on the type annotation.
- Business methods (`confirm`, `ship`) only **raise events** — they do
  not modify state directly.
- The `@apply` methods modify state — they are the *only* place where
  state changes happen.

This creates a clear separation:

- `confirm()` → raises `OrderConfirmed` → `when_confirmed()` sets status

## Event Application in Practice

### Creating an Aggregate

```python
order = Order.place("Alice", [...])
# 1. Creates the Order instance
# 2. Raises OrderPlaced event
# 3. @apply when_placed runs, sets status = "PENDING"
```

### Loading an Aggregate

When you load an event-sourced aggregate from the repository, Protean:

1. Reads all events for that aggregate from the event store
2. Creates a blank aggregate instance
3. Replays each event through the `@apply` methods in order
4. Returns the aggregate with its current state

```python
order = repo.get(order_id)
# Internally:
# 1. Read events: [OrderPlaced, OrderConfirmed]
# 2. Apply OrderPlaced → status = "PENDING"
# 3. Apply OrderConfirmed → status = "CONFIRMED"
# 4. Return order with status "CONFIRMED"
```

### Version Tracking

Each event increments the aggregate's version:

```python
order._version  # 0 after creation
# After OrderPlaced: version 1
# After OrderConfirmed: version 2
# After OrderShipped: version 3
```

Versions prevent concurrent modification — if two processes try to
modify the same aggregate, the second one will get a version conflict.

## The Event Store

Configure MessageDB (a PostgreSQL-based event store) in `domain.toml`:

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

The event store provides:

- **Streams**: each aggregate instance has its own stream
  (`order-a1b2c3d4`)
- **Categories**: all instances of an aggregate type share a category
  (`order`)
- **Global ordering**: events across all streams are globally ordered
- **Read positions**: consumers track where they left off

### Stream Categories

Protean derives stream names from the aggregate class name:

```python
@domain.aggregate(is_event_sourced=True, stream_category="order")
class Order:
    ...
```

Events for `Order(id="abc123")` are stored in stream `order-abc123`.

## Snapshots

Replaying hundreds of events can be slow. **Snapshots** solve this by
periodically saving the current state:

```toml
snapshot_threshold = 10
```

After 10 events, Protean saves a snapshot. On the next load:

1. Load the latest snapshot (instead of replaying all events)
2. Replay only events *after* the snapshot

This keeps load times fast even with long event histories.

## Fact Events

Not ready for full event sourcing? **Fact events** provide a middle
ground. They auto-generate an event that captures the aggregate's entire
state after each persistence:

```python
@domain.aggregate(fact_events=True)
class Book:
    title = String(max_length=200, required=True)
    author = String(max_length=150, required=True)
    ...
```

Each time a `Book` is saved, Protean auto-generates a `BookFactEvent`
containing the full state snapshot. Downstream consumers (projectors,
event handlers) can subscribe to these fact events.

Fact events are useful when:

- You want event-driven projections without full event sourcing
- You are migrating from traditional to event-sourced architecture
- External systems need state snapshots rather than granular events

## Summary

In this chapter you learned:

- **Event sourcing** stores events instead of state — current state is
  rebuilt by replaying events.
- **`is_event_sourced=True`** converts an aggregate to event-sourced.
- **`@apply`** methods define how each event type modifies state.
- The **event store** (MessageDB) persists events in streams organized
  by category.
- **Snapshots** optimize performance for long event histories.
- **Fact events** provide an event-driven bridge for traditional
  aggregates.

We have explored all of Protean's major features — from basic aggregates
to event sourcing. In the final chapter, we will cover **testing
strategies** to keep your domain correct as it evolves.

## Next

[Chapter 15: Testing Your Domain →](15-testing.md)
