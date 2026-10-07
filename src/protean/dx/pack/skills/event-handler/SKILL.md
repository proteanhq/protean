---
name: event-handler
description: Define a Protean event handler - a class that consumes domain events raised by aggregates and runs side effects such as syncing state across aggregates, sending notifications, or triggering downstream processes. Event handlers are associated with an aggregate via part_of or with a stream via stream_category, and use the @handle decorator to process specific event types. They are fire-and-forget and return no values. Also covers cross-aggregate synchronization via events, keeping one aggregate per transaction. Use when you need to react to a domain event, handle an event, process events from another aggregate, sync state between aggregates, implement eventual consistency, add notifications or side effects for domain events, or when the user asks to "create an event handler", "handle an event", "react to an event", "sync aggregates", "add a listener for events", "update another aggregate when X happens", "add cross-aggregate coordination", "when order ships reduce inventory", or "add an event-driven sync".
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
    confirmation_number: String()

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
8. **part_of uses class reference** - Handler uses `part_of=AggregateClass` by convention. A string reference (`part_of="AggregateName"`) also works and resolves at `init`, so the aggregate may be defined after the handler
9. **Hand off to another aggregate with a command** - To change aggregate B when aggregate A raises an event, put the handler in A's cluster (`part_of=A`, no `stream_category`) and have it call `current_domain.process(...)` with a command that belongs to B. B's command handler does the write. A handler in B's cluster that reacts to A's event is what `check` reports as `EVENT_HANDLER_FOREIGN_EVENT`

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

The handler sits in `Order`'s cluster, because `OrderShipped` belongs to `Order`.
It changes `Inventory` by issuing a `ReduceStock` command, which `Inventory`'s
command handler processes.

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

## Quick example: Multiple events

Each method issues a `SendNotification` command. The notification id is the
event's own id (`event._metadata.headers.id`), which stays the same when the
event is delivered again.

```python
@domain.event_handler(part_of=Account)
class AccountNotifier:
    @handle(AccountRegistered)
    def on_registered(self, event: AccountRegistered):
        current_domain.process(
            SendNotification(
                notification_id=event._metadata.headers.id,
                message=f"Welcome {event.name}!",
            )
        )

    @handle(AccountSuspended)
    def on_suspended(self, event: AccountSuspended):
        current_domain.process(
            SendNotification(
                notification_id=event._metadata.headers.id,
                message=f"Account suspended: {event.reason}",
            )
        )
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
@domain.event_handler(part_of=Shipment)
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
2. An **event handler in A's cluster** (`part_of=A`) reacts to that event
3. The handler issues a **command** that belongs to **Aggregate B**
4. B's **command handler** loads B and updates it in a **separate transaction** (eventual consistency)

| Approach | Correct? | Why |
|----------|----------|-----|
| Handler modifies source + target in one call | No | Two aggregates in one transaction |
| Handler in A's cluster issues a command to B | Yes | Each aggregate changes in its own transaction, through its own command handler |
| Handler in B's cluster listens to A's stream and writes B | No | `check` reports `EVENT_HANDLER_FOREIGN_EVENT`: the two clusters are coupled directly |
| Command handler loads and modifies two aggregates | No | Violates consistency boundary |

For a flow with several causally dependent steps, where each step waits on the
outcome of the one before, use a process manager. See
[process-manager](../process-manager/SKILL.md).

### Making the receiving end safe to repeat

Events are delivered at least once, so the same event can reach the handler
twice and issue the same command twice. The command carries a deterministic id
taken from the event, such as the order id. B's command handler returns without
changes when that work is already done:

- **When the command creates B**, give B that id and check for it first:
  `try: repository.get(command.order_id)`, add B on `ObjectNotFoundError`, and
  return otherwise.
- **When the command updates B**, keep a list of applied ids on B (for example
  `applied_order_ids: List(content_type=String)`). The command handler returns
  early when the id is already in the list, and the aggregate method appends it.

When one event drives several writes to B, derive one id per write, such as
`f"{order_id}:{product_id}"`. Never generate a fresh `uuid4()` in the handler,
because a redelivered event would then look like new work.

### Designing for eventual consistency

- **Include enough data in events**: the handler should not need to load the source aggregate
- **Make the receiving command handler safe to repeat**: see the section above
- **Accept brief staleness**: the UI might show slightly outdated data
- Use `domain.config["event_processing"] = "sync"` and `domain.config["command_processing"] = "sync"` for deterministic testing

### Common patterns

```
Order.ship()      → OrderShipped     → InventorySyncHandler (part_of=Order)      → ReduceStock          → Inventory.reduce_stock()
Payment.confirm() → PaymentConfirmed → SubscriptionSyncHandler (part_of=Payment) → ActivateSubscription → Subscription.activate()
Task.assign_to()  → TaskAssigned     → WorkloadSyncHandler (part_of=Task)        → RecordAssignment     → TeamMember.record_assignment()
```

### Building a cross-aggregate handler

The full runnable version, including the `ShipOrder` command and `Order`'s
command handler, is [cross_sync_order_inventory.py](assets/cross_sync_order_inventory.py).
A `ShipOrder` command ships the order, `Order` raises `OrderShipped`,
`InventorySyncHandler` in `Order`'s cluster issues `ReduceStock`, and
`InventoryCommandHandler` reduces the stock unless it has already applied that
order.

```python
# 1. Event on source aggregate
@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

# 2. Source aggregate raises event (Order's command handler calls ship())
@domain.aggregate
class Order:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="placed")

    def ship(self):
        self.status = "shipped"
        self.raise_(OrderShipped(
            order_id=self.id,
            product_id=self.product_id,
            quantity=self.quantity,
        ))

# 3. Command to the target aggregate carries the order id from the event
@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

# 4. Target aggregate records which orders it has applied
@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    stock_level: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id, quantity):
        self.stock_level -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]

# 5. Target's command handler does the write, and skips an order it has applied
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # a redelivered OrderShipped; reducing again would double count
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)

# 6. Event handler in the source's cluster hands off with the command
@domain.event_handler(part_of=Order)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        current_domain.process(ReduceStock(
            order_id=event.order_id,
            product_id=event.product_id,
            quantity=event.quantity,
        ))
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

### Handling another cluster's event (`EVENT_HANDLER_FOREIGN_EVENT`)

```python
# fragment
# Wrong! check reports EVENT_HANDLER_FOREIGN_EVENT
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        inventory = domain.repository_for(Inventory).find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        domain.repository_for(Inventory).add(inventory)
```

The handler belongs to `Inventory` but reacts to `Order`'s event, so the two
clusters are coupled directly. Instead: put the handler in `Order`'s cluster and
issue a `ReduceStock` command, as in
[Building a cross-aggregate handler](#building-a-cross-aggregate-handler).

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
        order = domain.repository_for(Order).get(event.order_id)
        domain.repository_for(Order).add(order)
```

Instead: Let the implicit UnitOfWork handle it

### Business logic in the handler

```python
@handle(OrderPlaced)
def confirm_order(self, event):
    order = domain.repository_for(Order).get(event.order_id)
    if order.status != "placed":  # Business logic leak!
        raise ValueError("Only placed orders can be confirmed")
    order.status = "confirmed"
    domain.repository_for(Order).add(order)
```

Instead: Keep business logic in the aggregate (an `order.confirm()` method), handler only orchestrates

### What `check` reports

`check` inspects your event handlers and reports these diagnostics:

- `EVENT_HANDLER_FOREIGN_EVENT`: the handler reacts to an event owned by another cluster, which couples the two clusters directly. Move the handler into the cluster that owns the event and have it issue a command that belongs to this cluster. For a flow with several causally dependent steps, use a `ProcessManager` that reacts to the source event and issues the command.
- `HANDLER_TOO_BROAD`: the handler handles more message types than the configured `[lint] handler_breadth_limit`, so it has grown into a catch-all. Split it into focused handlers, or raise the limit if the breadth is intentional.
- `HANDLER_PERSISTS_AND_CALLS_OUT`: one handler method calls an external system after its first `repository_for(...)`, so the call runs with the Unit of Work's transaction open, holding row locks and a pooled connection for as long as the call takes, and a retry re-runs the method and re-issues the call. A call made before any repository access runs outside the transaction and is not flagged. Split the method into one that persists and one that calls out; when the call must follow the write, raise an event from the persisting side and handle that instead.

## Detailed references

### Core Concepts
- [Same-Aggregate Handling](references/same-aggregate.md) - Handler processes events from its own aggregate
- [Cross-Aggregate Handling](references/cross-aggregate.md) - Handler in the event's own cluster changes another aggregate through a command
- [Eventual Consistency](references/eventual-consistency.md) - Trade-offs and guarantees
- [Cross-Aggregate Patterns](references/cross-aggregate-patterns.md) - Common sync scenarios
- [Error Handling](references/error-handling.md) - Custom error recovery with handle_error
- [Catch-All ($any) Handler](references/any-handler.md) - Processing any event on the stream
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Same-Aggregate Handler](assets/event_handler_same_aggregate.py) - Handler for its own aggregate's events
- [Cross-Aggregate Handler](assets/event_handler_cross_aggregate.py) - Order's handler sends Inventory a command when an order ships
- [Order-Inventory Sync](assets/cross_sync_order_inventory.py) - OrderShipped reduces Inventory stock
- [Payment-Subscription Sync](assets/cross_sync_payment_subscription.py) - PaymentConfirmed activates Subscription
- [Multi-Event Sync](assets/cross_sync_multi_event.py) - Multiple events from one source trigger different target updates
- [Multiple Events](assets/event_handler_multiple_events.py) - Handler with multiple @handle methods
- [Error Handling](assets/event_handler_error_handling.py) - Custom handle_error classmethod
- [Catch-All Handler](assets/event_handler_any_event.py) - @handle("$any") for all events

### Related Skills
- [event](../event/SKILL.md) - Events are the input to event handlers
- [aggregate](../aggregate/SKILL.md) - Event handlers are always connected to aggregates
- [command-handler](../command-handler/SKILL.md) - Analogous pattern for commands, and the write path a cross-aggregate handler hands off to
- [process-manager](../process-manager/SKILL.md) - Flows with several causally dependent steps across aggregates
- [refactor-introduce-events](../refactor-introduce-events/SKILL.md) - Refactoring direct calls into event-driven flows

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
