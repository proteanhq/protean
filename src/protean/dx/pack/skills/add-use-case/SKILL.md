---
name: add-use-case
description: Build a complete vertical slice in Protean - the full command flow from command definition through handler, aggregate mutation, event raising, and event handler reaction. This is the most common workflow for adding a new feature. Use when the user asks to "add a use case", "add a feature", "create a command flow", "implement a vertical slice", "add a new action", "build an end-to-end flow", "add command processing", or when they describe actions like "users should be able to place orders", "allow admins to approve requests", "implement the checkout flow".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [command, command-handler, aggregate, event, event-handler]
---

# Add Use Case

A use case in Protean follows the command flow pattern. Each use case is a vertical slice through the architecture:

```
Command → Command Handler → Aggregate Method → Event → Event Handler
```

## What this creates

| Component | Purpose | Decorator |
|-----------|---------|-----------|
| Command | Carries user intent and input data | `@domain.command(part_of=...)` |
| Command Handler | Receives command, orchestrates aggregate | `@domain.command_handler(part_of=...)` |
| Aggregate method | Mutates state, raises events | Method on `@domain.aggregate` |
| Event | Records what happened | `@domain.event(part_of=...)` |
| Event Handler | Reacts to what happened (side effects) | `@domain.event_handler(part_of=...)` |

## Information to gather

Before building a use case, understand:

- [ ] **What action does the user take?** — Name it as an imperative verb phrase (e.g., "Place Order", "Approve Request")
- [ ] **What data is required?** — Command fields (input from user/API)
- [ ] **Which aggregate does it modify?** — The aggregate that owns the business logic
- [ ] **What state change occurs?** — The mutation in the aggregate method
- [ ] **What happened after?** — The event to raise (past tense: "OrderPlaced", "RequestApproved")
- [ ] **What side effects follow?** — Event handler reactions (notifications, syncing, downstream updates)

## Process

### Step 1: Define the command

Commands are named as imperative verb phrases. They carry the data needed to perform the action. Use `part_of` to associate with the target aggregate.

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
```

**Key rules for commands** (see [command](../command/SKILL.md)):
- Named as imperative: `PlaceOrder`, `ApproveRequest`, `CancelSubscription`
- Fields are the input data, not the entire aggregate state
- `required=True` on mandatory fields — raises `InvalidDataError` if missing
- Use field constraints for basic validation (Layer 1)

### Step 2: Define the event

Events record what happened after the command was processed. Named in past tense.

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    total_amount: Float(required=True)
```

### Step 3: Add the aggregate method

The aggregate method encapsulates the business logic. It mutates state and raises the event.

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    total_amount: Float(default=0.0)
    status: String(default="placed")

    @classmethod
    def place(cls, customer_id, product_id, quantity, unit_price):
        """Factory method for placing a new order."""
        total = quantity * unit_price
        order = cls(
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            total_amount=total,
        )
        order.raise_(OrderPlaced(
            order_id=order.id,
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            total_amount=total,
        ))
        return order
```

### Step 4: Build the command handler

The command handler receives the command, orchestrates the aggregate, and persists it. Use `domain.process(command, asynchronous=False)` for synchronous processing.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order = Order.place(
            customer_id=command.customer_id,
            product_id=command.product_id,
            quantity=command.quantity,
            unit_price=10.0,  # In real code, look up from catalog
        )
        domain.repository_for(Order).add(order)
```

**Key rules for command handlers** (see [command-handler](../command-handler/SKILL.md)):
- `part_of=AggregateClass` (command handlers require the class reference — a string `part_of` raises at registration)
- Use `@handle(CommandClass)` decorator on each handler method
- Each handler method has signature `(self, command: CommandClass)`
- Implicit UnitOfWork — no manual transaction management needed
- Load aggregate → call method → persist via `repository_for().add()`

### Step 5: Add the event handler (optional)

Event handlers react to events for side effects: notifications, cross-aggregate updates, logging.

```python
@domain.event_handler(part_of=Notification, stream_category=Order.meta_.stream_category)
class OrderNotificationHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        notification = Notification(
            message=f"Order {event.order_id} placed for customer {event.customer_id}"
        )
        domain.repository_for(Notification).add(notification)
```

### Step 6: Process the command

```python
domain.process(
    PlaceOrder(
        order_id="ORD-001",
        customer_id="CUST-001",
        product_id="PROD-001",
        quantity=3,
    ),
    asynchronous=False,
)
```

## The command flow

```
1. API/UI creates Command with input data
2. domain.process(command) dispatches to Command Handler
3. Command Handler loads/creates Aggregate
4. Aggregate method mutates state and raises Event
5. Handler persists Aggregate (with events) via repository
6. Event is published to event store
7. Event Handler(s) pick up the event and react
```

## Use case patterns

### Create pattern (factory method)

```python
# Handler creates a new aggregate
@handle(PlaceOrder)
def handle(self, command):
    order = Order.place(...)  # Factory method
    domain.repository_for(Order).add(order)
```

### Update pattern (load and mutate)

```python
# Handler loads existing aggregate and calls method
@handle(ApproveOrder)
def handle(self, command):
    order = domain.repository_for(Order).get(command.order_id)
    order.approve(approved_by=command.approver_id)
    domain.repository_for(Order).add(order)
```

### Guard pattern (validation before action)

```python
# Handler validates context before aggregate operation
@handle(CancelOrder)
def handle(self, command):
    if command.requested_by_role not in ["admin", "customer"]:
        raise ValidationError({"authorization": ["Not authorized"]})
    order = domain.repository_for(Order).get(command.order_id)
    order.cancel(reason=command.reason)
    domain.repository_for(Order).add(order)
```

## Naming conventions

| Component | Convention | Example |
|-----------|-----------|---------|
| Command | Imperative verb phrase | `PlaceOrder`, `ApproveRequest` |
| Event | Past tense of command | `OrderPlaced`, `RequestApproved` |
| Handler class | `{Aggregate}CommandHandler` | `OrderCommandHandler` |
| Handler method | `handle_{command}` | `handle_place_order` |
| Aggregate factory | `cls.{verb}(...)` | `Order.place(...)` |
| Aggregate method | `self.{verb}(...)` | `order.approve(...)` |
| Event handler class | Descriptive name | `OrderNotificationHandler` |

## Common mistakes

### Business logic in the handler instead of the aggregate

```python
# Wrong! Business rule computed in the handler
@handle(PlaceOrder)
def handle(self, command):
    order = Order(customer_id=command.customer_id)
    order.total_amount = command.quantity * 10.0  # rule leaks into the handler
    order.status = "placed"
    domain.repository_for(Order).add(order)
```

Instead: keep the rule in an aggregate method/factory; the handler only orchestrates.

```python
@handle(PlaceOrder)
def handle(self, command):
    order = Order.place(customer_id=command.customer_id, quantity=command.quantity, unit_price=10.0)
    domain.repository_for(Order).add(order)
```

### Forgetting to raise the event

```python
# Wrong! State changes, but nothing is recorded or published
@classmethod
def place(cls, **kwargs):
    order = cls(**kwargs)
    return order  # no raise_()
```

Instead: raise the past-tense event so the fact is recorded and handlers can react: `order.raise_(OrderPlaced(...))`.

### Persisting multiple aggregates in one handler

```python
# Wrong! Two aggregates mutated and saved in one transaction
@handle(PlaceOrder)
def handle(self, command):
    order = Order.place(...)
    inventory.reduce(command.quantity)
    domain.repository_for(Order).add(order)
    domain.repository_for(Inventory).add(inventory)  # cross-aggregate write
```

Instead: persist one aggregate and coordinate the other via an event handler (eventual consistency); for an atomic cross-aggregate rule use a domain service.

### Authorization inside the aggregate

```python
# Wrong! Context/authorization baked into the domain model
def cancel(self, role):
    if role != "admin":
        raise ValidationError({"authorization": ["Not authorized"]})
```

Instead: guard authorization in the handler (Layer 4); keep the aggregate focused on invariants.

## Complete examples

- [Basic use case](assets/use_case_basic.py) — Command → Handler → Aggregate → Event (create pattern)
- [Use case with update](assets/use_case_with_update.py) — Load, mutate, and persist (update pattern with event handler)
- [Use case with guards](assets/use_case_with_guards.py) — Authorization guard + existence check in handler

## Detailed references

- [Vertical Slice Architecture](references/vertical-slice.md) — How command flow implements vertical slices
- [Command Flow Patterns](references/command-flow-patterns.md) — Create, update, and guard patterns

## Related skills

- [command](../command/SKILL.md) — Command definition and field validation
- [command-handler](../command-handler/SKILL.md) — Handler patterns
- [aggregate](../aggregate/SKILL.md) — Aggregate methods and event raising
- [event](../event/SKILL.md) — Event definition
- [event-handler](../event-handler/SKILL.md) — Event handler patterns
- [add-validation](../add-validation/SKILL.md) — Adding validation at each layer

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
