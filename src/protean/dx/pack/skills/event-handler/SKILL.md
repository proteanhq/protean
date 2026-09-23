---
name: event-handler
description: Define a Protean event handler - a class that consumes domain events raised by aggregates and orchestrates side effects such as syncing state across aggregates, sending notifications, or triggering downstream processes. Event handlers are always associated with an aggregate via part_of and use the @handle decorator to process specific event types. They follow a fire-and-forget pattern and do NOT return values. Also covers cross-aggregate synchronization - coordinating state between aggregates via events while maintaining one-aggregate-per-transaction boundaries. Use when you need to react to a domain event, handle an event, process events from another aggregate, sync state between aggregates, implement eventual consistency, add notifications or side effects for domain events, or when the user asks to "create an event handler", "handle an event", "react to an event", "sync aggregates", "add a listener for events", "update another aggregate when X happens", "add cross-aggregate coordination", "when order ships reduce inventory", or "add an event-driven sync".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - EVENT_HANDLER_FOREIGN_EVENT
    - HANDLER_TOO_BROAD
    - HANDLER_PERSISTS_AND_CALLS_OUT
---

# Event Handler

## Basic structure

```python
from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain()
domain.config["event_processing"] = "sync"

@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(default="draft")

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.order_id))

@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        repo.add(order)
```

## Key rules

1. **part_of or stream_category required** - Handler must be associated with an aggregate or stream: `@domain.event_handler(part_of=Order)`
2. **Use @handle decorator** - Each handler method is decorated with `@handle(EventClass)` or `@handle("$any")`
3. **Handler methods take self and event** - Signature: `def method_name(self, event: EventClass)`
4. **No return values** - Event handlers do NOT return values (CQRS pattern, fire-and-forget)
5. **Implicit UnitOfWork** - Each handler method runs within a UnitOfWork context automatically
6. **Multiple handlers per event** - Unlike commands, multiple event handlers can process the same event
7. **Import handle from protean** - `from protean import handle` (not from protean.core)
8. **part_of uses class reference** - Handler uses `part_of=AggregateClass` (not a string). Define the aggregate before the handler so the class resolves; unlike events/commands, event handlers do **not** accept a string `part_of` (it raises at registration)
9. **stream_category for cross-aggregate** - Use `stream_category=OtherAggregate.meta_.stream_category` to listen to another aggregate's events

## Handler options

| Option | Purpose | Required |
|--------|---------|----------|
| `part_of` | Associate handler with an aggregate class | Yes (unless stream_category provided) |
| `stream_category` | Stream to listen to, use `Aggregate.meta_.stream_category` (defaults to own aggregate's stream) | No |
| `source_stream` | Origin stream filter | No |
| `subscription_type` | "stream" or "event_store" | No |
| `subscription_profile` | "production", "fast", "batch", "debug", "projection" | No |
| `subscription_config` | Custom config dict (messages_per_tick, max_retries, etc.) | No |

## Quick example: Cross-aggregate handler

```python
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    @handle(OrderShipped)
    def reduce_stock_level(self, event: OrderShipped):
        repo = domain.repository_for(Inventory)
        inventory = repo._dao.find_by(book_id=event.book_id)
        inventory.in_stock -= event.quantity
        repo.add(inventory)
```

## Quick example: Multiple events

```python
@domain.event_handler(part_of=Notification, stream_category=Account.meta_.stream_category)
class AccountNotifier:
    @handle(AccountRegistered)
    def on_registered(self, event: AccountRegistered):
        notification = Notification(message=f"Welcome {event.name}!")
        domain.repository_for(Notification).add(notification)

    @handle(AccountSuspended)
    def on_suspended(self, event: AccountSuspended):
        notification = Notification(message=f"Account suspended: {event.reason}")
        domain.repository_for(Notification).add(notification)
```

## Quick example: Catch-all ($any) handler

```python
@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    @handle("$any")
    def on_any_event(self, event):
        audit = AuditLog(event_type=event.__class__.__name__)
        domain.repository_for(AuditLog).add(audit)
```

## Error handling

Override `handle_error` classmethod for custom error recovery during async processing:

```python
@domain.event_handler(part_of=ShipmentLog, stream_category=Shipment.meta_.stream_category)
class ShipmentNotifier:
    @handle(ShipmentDispatched)
    def on_dispatched(self, event):
        # ... handler logic ...
        pass

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        logger.error(f"Shipment event failed: {exc}")
```

## Cross-aggregate sync pattern

The primary use case for event handlers is coordinating state changes between aggregates
while maintaining the **one aggregate per transaction** rule.

### The principle

Never modify two aggregates in the same handler. Instead:

1. **Aggregate A** raises a domain event when its state changes
2. An **event handler** (belonging to Aggregate B) listens to that event
3. The handler loads **Aggregate B** and updates its state
4. This happens in a **separate transaction** (eventual consistency)

| Approach | Correct? | Why |
|----------|----------|-----|
| Handler modifies source + target in one call | No | Two aggregates in one transaction |
| Source raises event, handler on target reacts | Yes | Each handler = one aggregate transaction |
| Command handler loads and modifies two aggregates | No | Violates consistency boundary |

### Designing for eventual consistency

- **Include enough data in events** — The handler should not need to load the source aggregate
- **Make handlers idempotent** — Processing the same event twice should produce the same result
- **Accept brief staleness** — UI might show slightly outdated data
- Use `domain.config["event_processing"] = "sync"` for deterministic testing

### Common patterns

```
Order.ship()    → OrderShipped    → InventoryHandler    → Inventory.reduce_stock()
Payment.confirm() → PaymentConfirmed → SubscriptionHandler → Subscription.activate()
Task.assign()   → TaskAssigned    → WorkloadHandler     → TeamMember.increment_count()
```

### Building a cross-aggregate handler

```python
# 1. Event on source aggregate
@domain.event(part_of="Order")
class OrderShipped:
    order_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(required=True)

# 2. Source aggregate raises event
@domain.aggregate
class Order:
    def ship(self):
        self.status = "shipped"
        self.raise_(OrderShipped(
            order_id=self.id,
            product_id=self.product_id,
            quantity=self.quantity,
        ))

# 3. Handler on target aggregate listens to source stream
@domain.event_handler(
    part_of=Inventory,
    stream_category=Order.meta_.stream_category,
)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        inventory = domain.repository_for(Inventory).get(event.product_id)
        inventory.reduce_stock(event.quantity)
        domain.repository_for(Inventory).add(inventory)
```

## Common mistakes

### Missing part_of and stream_category

```python
@domain.event_handler  # Wrong! Missing both part_of and stream_category
class OrderEventHandler:
    pass
```

Instead: Always specify at least part_of or stream_category

```python
@domain.event_handler(part_of=Order)  # Correct!
class OrderEventHandler:
    pass
```

### Returning values from event handlers

```python
@handle(OrderPlaced)
def handle(self, event):
    return order  # Wrong! Return value is discarded
```

Instead: Update aggregates or emit new events to communicate results

### Manually wrapping in UnitOfWork

```python
@handle(OrderPlaced)
def handle(self, event):
    with UnitOfWork():  # Unnecessary! Already implicit
        inventory = domain.repository_for(Inventory).get(event.id)
        domain.repository_for(Inventory).add(inventory)
```

Instead: Let the implicit UnitOfWork handle it

### Business logic in the handler

```python
@handle(OrderShipped)
def reduce_stock(self, event):
    inventory = domain.repository_for(Inventory).get(event.id)
    if inventory.in_stock < event.quantity:  # Business logic leak!
        raise ValueError("Not enough stock")
    inventory.in_stock -= event.quantity
    domain.repository_for(Inventory).add(inventory)
```

Instead: Keep business logic in the aggregate, handler only orchestrates

### What `check` reports

`check` inspects your event handlers and reports these diagnostics:

- `EVENT_HANDLER_FOREIGN_EVENT`: the handler reacts to an event owned by another cluster, which couples the two clusters directly. Move the handler into the owning cluster, or introduce a `ProcessManager` that reacts to the source event and issues a command into this cluster.
- `HANDLER_TOO_BROAD`: the handler handles more message types than the configured `[lint] handler_breadth_limit`, so it has grown into a catch-all. Split it into focused handlers, or raise the limit if the breadth is intentional.
- `HANDLER_PERSISTS_AND_CALLS_OUT`: one handler method calls an external system after its first `repository_for(...)`, so the call runs with the Unit of Work's transaction open, holding row locks and a pooled connection for as long as the call takes, and a retry re-runs the method and re-issues the call. A call made before any repository access runs outside the transaction and is not flagged. Split the method into one that persists and one that calls out; when the call must follow the write, raise an event from the persisting side and handle that instead.

## Detailed references

### Core Concepts
- [Same-Aggregate Handling](references/same-aggregate.md) - Handler processes events from its own aggregate
- [Cross-Aggregate Handling](references/cross-aggregate.md) - Handler listens to another aggregate's events
- [Eventual Consistency](references/eventual-consistency.md) - Trade-offs and guarantees
- [Cross-Aggregate Patterns](references/cross-aggregate-patterns.md) - Common sync scenarios
- [Error Handling](references/error-handling.md) - Custom error recovery with handle_error
- [Catch-All ($any) Handler](references/any-handler.md) - Processing any event on the stream
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Same-Aggregate Handler](assets/event_handler_same_aggregate.py) - Handler for its own aggregate's events
- [Cross-Aggregate Handler](assets/event_handler_cross_aggregate.py) - Inventory reacts to Order events
- [Order-Inventory Sync](assets/cross_sync_order_inventory.py) - OrderShipped reduces Inventory stock
- [Payment-Subscription Sync](assets/cross_sync_payment_subscription.py) - PaymentConfirmed activates Subscription
- [Multi-Event Sync](assets/cross_sync_multi_event.py) - Multiple events from one source trigger different target updates
- [Multiple Events](assets/event_handler_multiple_events.py) - Handler with multiple @handle methods
- [Error Handling](assets/event_handler_error_handling.py) - Custom handle_error classmethod
- [Catch-All Handler](assets/event_handler_any_event.py) - @handle("$any") for all events

### Related Skills
- [event](../event/SKILL.md) - Events are the input to event handlers
- [aggregate](../aggregate/SKILL.md) - Event handlers are always connected to aggregates
- [command-handler](../command-handler/SKILL.md) - Analogous pattern for commands (compare/contrast)
- [refactor-introduce-events](../refactor-introduce-events/SKILL.md) - Refactoring direct calls into event-driven flows

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
