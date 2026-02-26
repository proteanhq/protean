# Migrating Between Architectures

Protean is designed so you can start simple and evolve your architecture
incrementally. This guide shows the concrete code transformations for each
migration step: **DDD to CQRS** and **CQRS to Event Sourcing**.

Each migration is additive -- you layer new capabilities on top of what
already works, without rewriting from scratch.

---

## DDD to CQRS

The core shift: replace direct application service calls with explicit
commands routed through `domain.process()`, and add read-optimized
projections.

### Step 1: Extract commands from application service methods

**Before (DDD):** Application services receive raw data and orchestrate
directly.

```python
@domain.application_service(part_of=Order)
class OrderService:
    @use_case
    def place_order(self, customer_id, items, total):
        order = Order(customer_id=customer_id, total=total)
        for item in items:
            order.add_item(**item)
        current_domain.repository_for(Order).add(order)
        return order
```

**After (CQRS):** Define an explicit command and move the logic to a command
handler.

```python
# 1. Define the command
@domain.command(part_of=Order)
class PlaceOrder:
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)


# 2. Create a command handler
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(
            customer_id=command.customer_id,
            total=command.total,
        )
        for item in command.items:
            order.add_item(**item)
        current_domain.repository_for(Order).add(order)
```

### Step 2: Route through domain.process()

**Before:** Calling the application service directly from your endpoint.

```python
@app.post("/orders")
async def create_order(payload: dict):
    service = OrderService()
    order = service.place_order(**payload)
    return {"id": order.id}
```

**After:** Build a command and hand it to the domain.

```python
@app.post("/orders", status_code=201)
async def create_order(payload: dict):
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}
```

!!! note
    Command handlers do not return values. If you need a synchronous
    response (e.g. the created ID), keep an application service for that
    specific endpoint and use command handlers for async flows.

### Step 3: Add events for side effects

Move cross-aggregate coordination from service methods to domain events.

```python
# On the aggregate
class Order(BaseAggregate):
    # ... fields ...

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.id, total=self.total))


# React in a separate handler
@domain.event_handler(part_of=Inventory)
class InventoryHandler:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        # Update inventory in its own transaction
        ...
```

### Step 4: Add projections for reads

Replace direct aggregate queries with purpose-built projections.

```python
# Define a read model
@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    total = Float()
    status = String()
    item_count = Integer()


# Populate it with a projector
@domain.projector(part_of=OrderSummary)
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced):
        current_domain.repository_for(OrderSummary).add(
            OrderSummary(
                order_id=event.order_id,
                customer_id=event.customer_id,
                total=event.total,
                status="placed",
                item_count=event.item_count,
            )
        )
```

### Migration checklist

- [ ] Identify application service methods that change state
- [ ] Create a command for each state-changing method
- [ ] Create command handlers (one per aggregate)
- [ ] Update endpoints to use `domain.process()`
- [ ] Move cross-aggregate side effects to event handlers
- [ ] Add projections for read-heavy queries
- [ ] Remove application services that are now redundant
- [ ] Run tests at each step to verify behavior is preserved

---

## CQRS to Event Sourcing

The core shift: instead of persisting aggregate state directly, persist the
events that produce that state. The aggregate reconstructs itself by
replaying events.

### Step 1: Mark the aggregate as event-sourced

```python
# Before (CQRS)
@domain.aggregate
class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()

# After (Event Sourcing)
@domain.aggregate(is_event_sourced=True)
class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()
```

### Step 2: Add @apply methods

Event-sourced aggregates must define `@apply` methods that reconstruct state
from events. These are the **only** place where state changes happen.

```python
@domain.aggregate(is_event_sourced=True)
class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()

    def place(self, customer_id, total):
        self.raise_(OrderPlaced(
            order_id=self.id,
            customer_id=customer_id,
            total=total,
        ))

    @apply(OrderPlaced)
    def on_placed(self, event: OrderPlaced):
        self.customer_id = event.customer_id
        self.total = event.total
        self.status = "placed"
```

The pattern is: **command method raises an event, `@apply` method mutates
state**. This separation ensures that replaying events from the store
produces the same aggregate state.

### Step 3: Update command handlers

Command handlers for event-sourced aggregates use the same pattern -- the
repository automatically loads from the event store and saves by appending
events.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(id=command.order_id)
        order.place(
            customer_id=command.customer_id,
            total=command.total,
        )
        current_domain.repository_for(Order).add(order)
```

### Step 4: Configure the event store

Add event store configuration to your `domain.toml`:

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

### Step 5: Mix patterns per aggregate

You don't have to migrate everything at once. Protean supports mixing CQRS
and Event Sourcing within the same domain -- each aggregate chooses its own
persistence strategy.

```python
# This aggregate uses event sourcing (full audit trail needed)
@domain.aggregate(is_event_sourced=True)
class Account(BaseAggregate):
    ...

# This aggregate uses regular CQRS (simple CRUD is sufficient)
@domain.aggregate
class CustomerProfile(BaseAggregate):
    ...
```

See the
[Architecture Decision](../../concepts/architecture/architecture-decision.md)
guide for criteria on which aggregates benefit from event sourcing.

### Migration checklist

- [ ] Identify aggregates that need audit trails or temporal queries
- [ ] Add `is_event_sourced=True` to those aggregates
- [ ] Ensure every state mutation goes through `raise_()` + `@apply`
- [ ] Configure the event store in `domain.toml`
- [ ] Verify projections still populate correctly (they consume events, so
      they should work unchanged)
- [ ] Add temporal query tests where needed (`at_version`, `as_of`)
- [ ] Run the full test suite

---

## General advice

**Migrate one aggregate at a time.** Don't try to move your entire domain in
one step. Pick the aggregate that benefits most from the next architecture
level and migrate it. The rest can follow later -- or stay where they are.

**Keep tests green at every step.** Each transformation above is small enough
to verify independently. Run your tests after each step, not just at the
end.

**The tutorials show the full picture.** If you want to see each architecture
in a complete application context:

- [CQRS Tutorial](../getting-started/tutorial/index.md) -- 22 chapters
  building a bookshelf app from DDD through CQRS
- [Event Sourcing Tutorial](../getting-started/es-tutorial/index.md) -- 22
  chapters building a banking app with full event sourcing
