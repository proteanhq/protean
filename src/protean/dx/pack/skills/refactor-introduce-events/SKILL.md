---
name: refactor-introduce-events
description: >
  Introduce domain events to replace direct cross-aggregate calls, tight coupling, and synchronous
  side effects. Detects transaction boundary violations — handlers that modify multiple aggregates —
  and refactors them into event-driven flows with proper aggregate isolation. Use when the user
  says "introduce events", "add events", "decouple aggregates", "fix transaction boundary",
  "two aggregates in one handler", "make it event-driven", "break the coupling",
  or when an audit identifies transaction boundary violations or missing events.
license: Apache-2.0
compatibility: "Requires Python 3.11+, protean framework"
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [event, event-handler, aggregate, command-handler]
  diagnostic_codes: [EVENT_WITHOUT_DATA, UNRAISED_EVENT]
---

# Refactor: Introduce Events

> **Illustrative, guided refactoring.** This is a before→after walkthrough, not an
> automated transform: recognize the smell and apply the change yourself, adapting to the
> code at hand. The `introduce_events_*_before.py` asset is the intentional starting point
> (cross-aggregate coupling); the `*_after.py` asset shows the event-driven target.

Replace direct cross-aggregate calls with domain events and event handlers, establishing
proper transaction boundaries and enabling eventual consistency.

## What this produces

| Output | Purpose |
|--------|---------|
| **Domain events** | `@domain.event` classes for each state change |
| **Event raises** | `self.raise_()` calls in aggregate methods |
| **Event handlers** | `@domain.event_handler` for cross-aggregate side effects |
| **Updated handlers** | Single-aggregate command handlers |

## Detection patterns

### Transaction boundary violation

The primary signal — a handler that modifies two or more aggregate types:

```python
# fragment
# RED FLAG: two aggregates modified in one handler
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)
    domain.repository_for(Order).add(order)

    # VIOLATION: second aggregate in same transaction
    inventory = domain.repository_for(Inventory).get(command.product_id)
    inventory.reduce(command.quantity)
    domain.repository_for(Inventory).add(inventory)
```

### Direct side effects

Operations that should be reactions to events but are coded as direct calls:

```python
# fragment
# RED FLAG: side effects in command handler
@handle(CompleteOrder)
def complete_order(self, command):
    order = domain.repository_for(Order).get(command.order_id)
    order.complete()
    domain.repository_for(Order).add(order)

    # These should be event-driven reactions
    send_confirmation_email(order)
    update_analytics(order)
    notify_warehouse(order)
```

### Tight coupling between aggregates

Aggregate methods that reference other aggregates:

```python
# fragment
# RED FLAG: aggregate knows about another aggregate
class Order:
    def place(self):
        self.status = "PLACED"
        # Aggregate should not access other aggregates
        inventory = domain.repository_for(Inventory).get(self.product_id)
        inventory.reduce(self.quantity)
```

## Process

### Step 1: Identify the boundary violation

Map which aggregates are modified in the handler:

```
place_order handler:
  ├── Order (create + persist)     ← Source aggregate
  └── Inventory (load + mutate + persist)  ← Should be event-driven
```

The steps below use the handler's `PlaceOrder` command, the `Inventory` aggregate
it reaches into, and the `ReserveStock` command that `Inventory` will handle:

```python
@domain.command(part_of="Order")
class PlaceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
    unit_price = Float(required=True)


@domain.aggregate
class Inventory:
    product_id = String(required=True, identifier=True)
    available = Integer(default=0)
    reserved_order_ids = List(content_type=String)

    def reserve(self, order_id: str, quantity: int) -> None:
        if self.available < quantity:
            raise ValueError("Insufficient stock")
        self.available -= quantity
        self.reserved_order_ids = [*self.reserved_order_ids, order_id]


@domain.command(part_of="Inventory")
class ReserveStock:
    order_id = Identifier(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
```

### Step 2: Define the domain event

Create an event representing what happened to the source aggregate:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
    total_amount = Float(required=True)
```

**Event naming**: past tense of what happened — `OrderPlaced`, `PaymentProcessed`, `TicketEscalated`.

**Event fields**: include everything the event handler needs. The handler shouldn't need to
look up the source aggregate to get context.

An event with no fields carries nothing beyond its name, so a handler cannot react to what
actually changed. `check` reports that as `EVENT_WITHOUT_DATA`. Add the fields that capture
the change, or confirm the event is meant as a bare signal.

### Step 3: Raise the event in the source aggregate

```python
@domain.aggregate
class Order:
    customer_id = String(required=True)
    status = String(default="DRAFT")
    total = Float(default=0.0)

    def place(self, product_id: str, quantity: int, price: float) -> None:
        self.status = "PLACED"
        self.total = price * quantity
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                product_id=product_id,
                quantity=quantity,
                total_amount=self.total,
            )
        )
```

Raise the event from the aggregate or entity method that makes the change it records. An
event nothing raises there is reported as `UNRAISED_EVENT`. The check reads only aggregate
and entity method bodies, so an event raised from a command handler, a subscriber, or a
module-level factory still shows up; that is the signal to move the raise onto the aggregate
method, which is the refactor this skill performs.

### Step 4: React in the source cluster and hand off with a command

The event handler sits in `Order`'s cluster, because it reacts to `Order`'s own
event. It issues a command to `Inventory`, and `Inventory`'s command handler does
the write:

```python
@domain.event_handler(part_of=Order)
class InventoryReservation:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )
```

Events are delivered at least once, so the receiving command handler must be safe
to repeat. `ReserveStock` carries the order id from the event. `Inventory` keeps
the order ids it has already reserved stock for, and the handler returns without
changes when it sees one again:

```python
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.reserved_order_ids:
            return   # already reserved for this order
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)
```

`Inventory.reserve()` reduces the stock and appends the order id to
`reserved_order_ids`. Use the order id from the event, never a fresh `uuid4()`,
or a repeat cannot be recognized.

Key points:
- `part_of` = the cluster that owns the event (Order), with no `stream_category`
- The command is `part_of` the **target** aggregate (Inventory)
- Each handler loads and mutates only its own aggregate

A handler in `Inventory`'s cluster that handles `OrderPlaced` is what `check`
reports as `EVENT_HANDLER_FOREIGN_EVENT`. For a flow with several causally
dependent steps, use a [process manager](../process-manager/SKILL.md).

### Step 5: Slim down the command handler

Remove the cross-aggregate logic — the event handler takes over:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id)
        order.place(
            product_id=command.product_id,
            quantity=command.quantity,
            price=command.unit_price,
        )
        domain.repository_for(Order).add(order)
        # Inventory update happens via OrderPlaced event handler
```

### Step 6: Configure sync processing for tests

```python
# In conftest.py or test setup
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"
```

This ensures events, and the commands their handlers issue, are processed inline
during tests.

## Common mistakes

1. **Event too thin** — Including only the aggregate ID in the event forces the handler
   to look up the source aggregate, defeating the purpose. Include all data the handler needs.

2. **Event too fat** — Including the entire aggregate state in every event wastes space
   and couples consumers to the full schema. Include only what changed and context needed.

3. **Putting the event handler in the target's cluster.** A handler with
   `part_of=Inventory` that handles `OrderPlaced` is what `check` reports as
   `EVENT_HANDLER_FOREIGN_EVENT`. Keep the handler in `Order`'s cluster and hand
   off to `Inventory` with a command.

4. **Returning values from event handlers** — Event handlers are fire-and-forget. They
   don't return values. If you need a return, use a command handler.

5. **Circular events** — A handles B's events, B handles A's events. This creates
   infinite loops. Design event flows as DAGs (directed acyclic graphs).

## Quick example

```python
# fragment
# BEFORE: direct coupling
@handle(ShipOrder)
def ship_order(self, command):
    order = domain.repository_for(Order).get(command.order_id)
    order.ship(tracking_number=command.tracking)
    domain.repository_for(Order).add(order)
    # VIOLATION
    notification = domain.repository_for(Notification).get(order.customer_id)
    notification.add_message(f"Order {order.id} shipped!")
    domain.repository_for(Notification).add(notification)

# AFTER: event-driven
@handle(ShipOrder)
def ship_order(self, command):
    order = domain.repository_for(Order).get(command.order_id)
    order.ship(tracking_number=command.tracking)  # Raises OrderShipped
    domain.repository_for(Order).add(order)

@handle(OrderShipped)  # In an event handler with part_of=Order
def notify_customer(self, event):
    domain.process(
        AddNotificationMessage(
            order_id=event.order_id,
            customer_id=event.customer_id,
            message=f"Order {event.order_id} shipped!",
        )
    )

@handle(AddNotificationMessage)  # In Notification's command handler
def add_message(self, command):
    notification = domain.repository_for(Notification).get(command.customer_id)
    if command.order_id in notification.notified_order_ids:
        return  # already notified for this order
    notification.add_message(command.order_id, command.message)
    domain.repository_for(Notification).add(notification)
```

## Examples

- E-commerce: [before](assets/introduce_events_ecommerce_before.py) and [after](assets/introduce_events_ecommerce_after.py)

## Detailed references

- [Event design guide](references/event-design-guide.md) — How to design good events
- [Anti-patterns](references/anti-patterns.md) — Common mistakes when introducing events

## Related skills

- [event](../event/SKILL.md) — Event definition patterns
- [event-handler](../event-handler/SKILL.md) — Event handler patterns
- [audit-domain](../audit-domain/SKILL.md) — Detects transaction boundary violations

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
