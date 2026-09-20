---
name: add-event
description: Add a complete event flow to an existing aggregate - creates a domain event, adds or updates an aggregate method that raises the event via self.raise_(), and wires an event handler that processes the event and performs specified side effects (such as syncing state across aggregates, sending notifications, or triggering downstream processes). This is the primary workflow for adding reactive, event-driven behavior to a Protean domain. Use when the user wants to "add an event", "add a domain event", "add a reaction to a state change", "add a side effect", "create an event flow", "wire an event handler", "add event-driven behavior", "react to a state change", "sync aggregates on event", or describes something that happened or should happen (like "when an order is placed, reduce inventory", "after payment is confirmed, send a notification", "when a user registers, create a welcome email", "notify the warehouse when an order ships"). This workflow composes the event, aggregate, and event-handler element skills.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [event, aggregate, event-handler]
---

# Add Event Flow

This workflow adds a complete event flow to an existing aggregate. It creates three artifacts that work together:

1. **Event** - An immutable fact representing a state change (e.g., `OrderPlaced`)
2. **Aggregate method** - A method on the aggregate that performs the state change and raises the event via `self.raise_()`
3. **Event Handler** - A class that consumes the event and orchestrates side effects

## What this creates

| Artifact | Role | File location |
|----------|------|---------------|
| Event class | Captures what happened (immutable fact) | `<aggregate_folder>/<event_name_snake>.py` |
| Aggregate method | Performs state change, raises the event | `<aggregate_folder>/<aggregate>.py` (existing file) |
| Event Handler | Reacts to event, orchestrates side effects | Same file as event (same-aggregate) or `<aggregate_folder>/handle_<event_name_snake>.py` (cross-aggregate) |

## Information to gather

Before generating, ensure you know the following. **If any item is unknown, ask the user before proceeding.**

- [ ] **Source aggregate** - Which aggregate raises the event? (must already exist)
- [ ] **Triggering action** - What state change triggers the event? (which aggregate method, new or existing?)
- [ ] **Event name** - Past-tense verb + noun (e.g., `OrderPlaced`, `PaymentConfirmed`, `UserRegistered`)
- [ ] **Event fields** - What data should the event carry? (IDs, relevant state at time of change)
- [ ] **Side effect(s)** - What should happen when the event occurs? (update state, sync aggregates, send notification, etc.)
- [ ] **Handler location** - Does the side effect target the same aggregate or a different one?
- [ ] **Target aggregate** - If cross-aggregate, which aggregate does the handler belong to? (must already exist)

### Questions to ask when context is missing

If the user says "add an event to Order" without further detail, ask:

1. **"What state change should trigger this event?"** - e.g., "when the order is placed", "when payment is confirmed"
2. **"What data should the event carry?"** - e.g., order_id, customer_id, total_amount
3. **"What should happen when this event occurs?"** - e.g., "reduce inventory", "send confirmation email", "update a dashboard"
4. **"Does the side effect modify the same aggregate or a different one?"** - determines same-aggregate vs. cross-aggregate handler pattern

If the user describes a full scenario like "when an order is placed, reduce inventory stock", you can infer:
- Source aggregate: Order
- Event: OrderPlaced
- Side effect: reduce stock in Inventory
- Handler location: cross-aggregate (Inventory handler listening to Order stream)

## Process

### Step 1: Define the Event

Follow the patterns in [event](../event/SKILL.md).

Key points for this workflow:
- Name with past-tense verb: `OrderPlaced`, `PaymentConfirmed`, `UserRegistered`
- Always specify `part_of="AggregateName"` (string, not class reference)
- Include only data necessary to describe what happened (IDs, relevant state)
- Events are DTOs - only simple fields and value objects, no `HasOne`/`HasMany`
- Use `__version__ = 1` for schema evolution

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
```

### Step 2: Add or update the aggregate method

Follow the patterns in [aggregate](../aggregate/SKILL.md).

Key points for this workflow:
- The aggregate method performs the state change **and** raises the event
- Use `self.raise_(EventClass(...))` to raise the event
- Place business logic (guards, validations) in the aggregate method, before raising
- The event should be raised **after** the state change succeeds
- If the method already exists, add the `self.raise_()` call to it

```python
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total_amount: Float()

    def place(self):
        if self.status != "draft":
            raise ValueError("Order already placed")
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total_amount=self.total_amount,
        ))
```

### Step 3: Define the Event Handler

Follow the patterns in [event-handler](../event-handler/SKILL.md).

Key points for this workflow:
- Use `part_of=AggregateClass` (class reference, not string)
- Use `@handle(EventClass)` decorator on handler methods
- **Same-aggregate handler**: `@domain.event_handler(part_of=Order)` - listens to Order's own stream
- **Cross-aggregate handler**: `@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)` - Inventory handler listens to Order stream
- Event handlers do NOT return values (fire-and-forget)
- Each handler runs within an implicit UnitOfWork - no manual wrapping
- Multiple handlers can process the same event (unlike commands)

```python
# Same-aggregate handler
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        order = domain.repository_for(Order).get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        domain.repository_for(Order).add(order)

# Cross-aggregate handler
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventoryHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        inventory = domain.repository_for(Inventory)._dao.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        domain.repository_for(Inventory).add(inventory)
```

### Step 4: Wire together

All three components connect through the domain's event system:
1. Aggregate method performs state change and calls `self.raise_(event)`
2. When aggregate is persisted via repository, events are dispatched
3. Domain matches events to handlers based on stream category and `@handle` decorators
4. Handler loads target aggregate, performs side effect, persists

```
Aggregate Method → self.raise_(Event) → repository.add(aggregate)
                                              ↓
                                    Domain dispatches event
                                              ↓
                                    Event Handler receives event
                                              ↓
                                    Load target aggregate from repo
                                              ↓
                                    Perform side effect
                                              ↓
                                    Persist target aggregate
```

### Step 5: Configure event processing

For synchronous processing (recommended for testing and simple flows):

```python
domain.config["event_processing"] = "sync"
```

For asynchronous processing (production with message broker):

```python
domain.config["event_processing"] = "async"
```

## File organization (Screaming Architecture)

Colocate event definitions with their aggregate. Place event handlers based on which aggregate they belong to:

```
src/myapp/order/
├── order.py                    # Aggregate (with raise_() calls)
├── order_placed.py             # OrderPlaced event + same-aggregate handler (if any)
├── order_shipped.py            # OrderShipped event
└── order_api.py                # API endpoints

src/myapp/inventory/
├── inventory.py                # Inventory aggregate
├── handle_order_placed.py      # Cross-aggregate handler (listens to Order events)
└── inventory_api.py
```

**Naming conventions**:
- Event file: `<event_name_snake>.py` (e.g., `order_placed.py`)
- Same-aggregate handler: colocated in event file
- Cross-aggregate handler: `handle_<event_name_snake>.py` in the **target** aggregate's folder

## Adding to an existing event handler

When the aggregate already has an event handler, add the new `@handle` method to the existing handler class. Multiple `@handle` methods in one handler class is fine.

```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced): ...

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        order = domain.repository_for(Order).get(event.order_id)
        order.tracking_number = f"TRACK-{event.order_id}"
        domain.repository_for(Order).add(order)
```

## Key rules

1. **Events use `part_of="String"`**, handlers use `part_of=ClassRef` (event handlers require the class — a string `part_of` raises at registration) - don't mix them up
2. **Events are past-tense** (`OrderPlaced`), commands are imperative (`PlaceOrder`)
3. **Multiple handlers per event** - Unlike commands, the same event can be handled by many handlers
4. **Event handlers do NOT return values** - Fire-and-forget pattern
5. **Implicit UnitOfWork** - Do NOT wrap handler methods in manual UnitOfWork
6. **Business logic in aggregates** - Handlers only orchestrate (load, call method, persist)
7. **Raise events after state change** - Call `self.raise_()` after the aggregate state is updated
8. **Cross-aggregate uses stream_category** - `stream_category=SourceAggregate.meta_.stream_category`
9. **Sync processing for dev/test** - Set `domain.config["event_processing"] = "sync"`
10. **Events carry minimal data** - Only IDs and data needed by consumers, not entire aggregate state

## Common mistakes

- **Imperative event names** - Use `OrderPlaced` (past-tense), not `PlaceOrder` (that's a command)
- **Raising events outside aggregates** - Events must be raised via `self.raise_()` within aggregate methods
- **Business logic in event handlers** - Keep logic in aggregates; handlers only orchestrate
- **Returning values from event handlers** - Event handlers are fire-and-forget
- **Manual UnitOfWork in handlers** - It's implicit, don't wrap
- **Missing stream_category for cross-aggregate** - Without it, handler only sees its own aggregate's events
- **Raising events before state change** - State should change first, then raise the event

## Complete examples

- [Same-aggregate event flow](references/same-aggregate-flow.md) - Event + handler within one aggregate
- [Cross-aggregate event flow](references/cross-aggregate-flow.md) - Event triggers side effect in another aggregate
- [Multiple events flow](references/multiple-events-flow.md) - Multiple events from one aggregate with multiple handlers

### Asset files
- [add_event_same_aggregate.py](assets/add_event_same_aggregate.py) - Complete same-aggregate flow
- [add_event_cross_aggregate.py](assets/add_event_cross_aggregate.py) - Complete cross-aggregate flow
- [add_event_multiple_events.py](assets/add_event_multiple_events.py) - Multiple events with multiple handlers

## Related skills

- [event](../event/SKILL.md) — Event definition, fields, and past-tense naming
- [event-handler](../event-handler/SKILL.md) — Reacting to events and orchestrating side effects
- [aggregate](../aggregate/SKILL.md) — Raising events from aggregate methods

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
