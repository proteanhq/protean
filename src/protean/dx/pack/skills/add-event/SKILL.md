---
name: add-event
description: Add a complete event flow to an existing aggregate - creates a domain event, adds or updates an aggregate method that raises the event via self.raise_(), and wires an event handler that processes the event and performs specified side effects (such as syncing state across aggregates, sending notifications, or triggering downstream processes). This is the primary workflow for adding reactive, event-driven behavior to a Protean domain. Use when the user wants to "add an event", "add a domain event", "add a reaction to a state change", "add a side effect", "create an event flow", "wire an event handler", "add event-driven behavior", "react to a state change", "sync aggregates on event", or describes something that happened or should happen (like "when an order is placed, reduce inventory", "after payment is confirmed, send a notification", "when a user registers, create a welcome email", "notify the warehouse when an order ships"). This workflow composes the event, aggregate, and event-handler element skills.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [event, aggregate, event-handler, command, command-handler]
---

# Add Event Flow

This workflow adds a complete event flow to an existing aggregate. It creates these artifacts, which work together:

1. **Event** - An immutable fact representing a state change (e.g., `OrderPlaced`)
2. **Aggregate method** - A method on the aggregate that performs the state change and raises the event via `self.raise_()`
3. **Event Handler** - A class that consumes the event and orchestrates side effects
4. **Command and command handler** (cross-aggregate only) - The command the event handler issues, and the target aggregate's handler that does the write

## What this creates

| Artifact | Role | File location |
|----------|------|---------------|
| Event class | Captures what happened (immutable fact) | `<aggregate_folder>/<event_name_snake>.py` |
| Aggregate method | Performs state change, raises the event | `<aggregate_folder>/<aggregate>.py` (existing file) |
| Event Handler | Reacts to event, orchestrates side effects | Same file as event (same-aggregate) or `<aggregate_folder>/handle_<event_name_snake>.py` (cross-aggregate), always in the source aggregate's folder |
| Command + command handler (cross-aggregate) | Carries the change to the target aggregate, which does the write | `<target_folder>/<command_name_snake>.py` |

## Information to gather

Before generating, ensure you know the following. **If any item is unknown, ask the user before proceeding.**

- [ ] **Source aggregate** - Which aggregate raises the event? (must already exist)
- [ ] **Triggering action** - What state change triggers the event? (which aggregate method, new or existing?)
- [ ] **Event name** - Past-tense verb + noun (e.g., `OrderPlaced`, `PaymentConfirmed`, `UserRegistered`)
- [ ] **Event fields** - What data should the event carry? (IDs, relevant state at time of change)
- [ ] **Side effect(s)** - What should happen when the event occurs? (update state, sync aggregates, send notification, etc.)
- [ ] **Handler location** - Does the side effect target the same aggregate or a different one?
- [ ] **Target aggregate** - If cross-aggregate, which aggregate does the change land on? (must already exist; it receives a command)

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
- Handler location: cross-aggregate (a handler in Order's cluster issues a `ReduceStock` command to Inventory)

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
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
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
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="draft")
    total_amount: Float(required=True)
    confirmation_number: String()
    tracking_number: String()

    def place(self):
        if self.status != "draft":
            raise ValueError("Order already placed")
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            product_id=self.product_id,
            quantity=self.quantity,
            total_amount=self.total_amount,
        ))
```

### Step 3: Define the Event Handler

Follow the patterns in [event-handler](../event-handler/SKILL.md).

Key points for this workflow:
- Use `part_of=AggregateClass` when the class is in scope. A string reference also works and resolves at `init`
- Use `@handle(EventClass)` decorator on handler methods
- The handler always sits in the cluster that owns the event: `@domain.event_handler(part_of=Order)` for an `Order` event
- **Same-aggregate handler**: loads the aggregate, calls a method, persists
- **Cross-aggregate handler**: issues a command with `current_domain.process(...)`. The command is `part_of` the target aggregate, and the target's command handler does the write
- Events are delivered at least once, so the command carries an id taken from the event, and the target's command handler returns without changes when that work is already done
- Event handlers do NOT return values (fire-and-forget)
- Each handler runs within an implicit UnitOfWork - no manual wrapping
- Multiple handlers can process the same event (unlike commands)

The cross-aggregate example below needs a target aggregate. Here `Inventory` tracks stock per product:

```python
@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    in_stock: Integer(required=True)

    def reduce_stock(self, quantity: int):
        if quantity > self.in_stock:
            raise ValueError(f"Insufficient stock: have {self.in_stock}, need {quantity}")
        self.in_stock -= quantity
```

```python
# Same-aggregate handler
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        order = domain.repository_for(Order).get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        domain.repository_for(Order).add(order)

# Cross-aggregate handler: still in Order's cluster, hands off with a command
@domain.event_handler(part_of=Order)
class InventorySyncHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )
```

### Step 4 (cross-aggregate only): Add the command and the target's command handler

Follow the patterns in [command](../command/SKILL.md) and [command-handler](../command-handler/SKILL.md).

The command is `part_of` the target aggregate. It carries the source's id (here `order_id`), so a redelivered event reissues the same command. Reducing stock is an update, so `Inventory` keeps a list of the order ids it has applied, and its command handler returns early for one it has seen:

```python
@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied; a redelivered event must not reduce twice
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

`Inventory.reduce_stock` lowers the stock and appends the order id to `applied_order_ids: List(content_type=String)`. When the command creates an aggregate, give the new aggregate an id taken from the event and skip the add when `repository.get` finds it (see [split-aggregate](../split-aggregate/SKILL.md)). For a flow with several causally dependent steps, use a [process manager](../process-manager/SKILL.md).

### Step 5: Wire together

The components connect through the domain's event system:
1. Aggregate method performs state change and calls `self.raise_(event)`
2. When aggregate is persisted via repository, events are dispatched
3. Domain matches events to handlers based on stream category and `@handle` decorators
4. Handler performs the side effect. A same-aggregate handler loads, mutates and persists. A cross-aggregate handler issues a command, and the target's command handler loads, mutates and persists

```
Aggregate Method → self.raise_(Event) → repository.add(aggregate)
                                              ↓
                                    Domain dispatches event
                                              ↓
                                    Event Handler receives event
                                              ↓
                          (cross-aggregate) domain.process(Command)
                                              ↓
                          Target's command handler loads target aggregate
                                              ↓
                                    Perform side effect
                                              ↓
                                    Persist target aggregate
```

### Step 6: Configure event processing

For synchronous processing (recommended for testing and simple flows):

```python
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"  # for the cross-aggregate command
```

For asynchronous processing (production with message broker):

```python
domain.config["event_processing"] = "async"
domain.config["command_processing"] = "async"
```

## File organization (Screaming Architecture)

Colocate event definitions with their aggregate. Event handlers live with the aggregate that owns the event. Commands and command handlers live with the aggregate they change:

```
src/myapp/order/
├── order.py                    # Aggregate (with raise_() calls)
├── order_placed.py             # OrderPlaced event + same-aggregate handler (if any)
├── handle_order_placed.py      # Cross-aggregate handler (issues ReduceStock)
├── order_shipped.py            # OrderShipped event
└── order_api.py                # API endpoints

src/myapp/inventory/
├── inventory.py                # Inventory aggregate
├── reduce_stock.py             # ReduceStock command + its command handler
└── inventory_api.py
```

**Naming conventions**:
- Event file: `<event_name_snake>.py` (e.g., `order_placed.py`)
- Same-aggregate handler: colocated in event file
- Cross-aggregate handler: `handle_<event_name_snake>.py` in the **source** aggregate's folder
- Command the handler issues: `<command_name_snake>.py` in the **target** aggregate's folder

## Adding to an existing event handler

When the aggregate already has an event handler, add the new `@handle` method to the existing handler class. Multiple `@handle` methods in one handler class is fine.

```python
@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)

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

1. **Events use `part_of="String"`** - Handlers usually pass the class, `part_of=ClassRef`, and a string works on a handler too
2. **Events are past-tense** (`OrderPlaced`), commands are imperative (`PlaceOrder`)
3. **Multiple handlers per event** - Unlike commands, the same event can be handled by many handlers
4. **Event handlers do NOT return values** - Fire-and-forget pattern
5. **Implicit UnitOfWork** - Do NOT wrap handler methods in manual UnitOfWork
6. **Business logic in aggregates** - Handlers only orchestrate (load, call method, persist)
7. **Raise events after state change** - Call `self.raise_()` after the aggregate state is updated. An event-sourced aggregate is the exception: it raises the event first, and `@apply` changes the state (see the `event-sourced-aggregate` skill)
8. **Cross-aggregate goes through a command** - The handler sits in the source's cluster and issues a command that the target's command handler processes. The command carries an id from the event, and the target's command handler returns without changes when that work is already done
9. **Sync processing for dev/test** - Set `domain.config["event_processing"] = "sync"`
10. **Events carry minimal data** - Only IDs and data needed by consumers, not entire aggregate state

## Common mistakes

- **Imperative event names** - Use `OrderPlaced` (past-tense), not `PlaceOrder` (that's a command)
- **Raising events outside aggregates** - Events must be raised via `self.raise_()` within aggregate methods
- **Business logic in event handlers** - Keep logic in aggregates; handlers only orchestrate
- **Returning values from event handlers** - Event handlers are fire-and-forget
- **Manual UnitOfWork in handlers** - It's implicit, don't wrap
- **Putting the handler in the target's cluster** - A handler that is `part_of` the target aggregate and reacts to the source's event is what `check` reports as `EVENT_HANDLER_FOREIGN_EVENT`. Keep the handler in the source's cluster and issue a command
- **Generating a fresh id in the handler** - Events are delivered at least once, so a `uuid4()` per delivery writes the change twice. Take the id from the event
- **Raising events before state change** - State should change first, then raise the event. This does not apply to an event-sourced aggregate, where the event is raised first and `@apply` changes the state

## Complete examples

- [Same-aggregate event flow](references/same-aggregate-flow.md) - Event + handler within one aggregate
- [Cross-aggregate event flow](references/cross-aggregate-flow.md) - Event triggers a command to another aggregate
- [Multiple events flow](references/multiple-events-flow.md) - Multiple events from one aggregate with multiple handlers

### Asset files
- [add_event_same_aggregate.py](assets/add_event_same_aggregate.py) - Complete same-aggregate flow
- [add_event_cross_aggregate.py](assets/add_event_cross_aggregate.py) - Complete cross-aggregate flow
- [add_event_multiple_events.py](assets/add_event_multiple_events.py) - Multiple events with multiple handlers

## Related skills

- [event](../event/SKILL.md): Event definition, fields, and past-tense naming
- [event-handler](../event-handler/SKILL.md): Reacting to events and orchestrating side effects
- [aggregate](../aggregate/SKILL.md): Raising events from aggregate methods
- [command](../command/SKILL.md) and [command-handler](../command-handler/SKILL.md): The command a cross-aggregate handler issues, and its handler
- [process-manager](../process-manager/SKILL.md): Flows with several causally dependent steps

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
