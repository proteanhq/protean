# Creating Identities Early

## The Problem

In many systems, identity is an afterthought -- a database-generated auto-increment
integer assigned at the moment of persistence. The aggregate doesn't know its own
identity until it has been saved, and callers don't learn the identity until the
save completes.

This creates a cascade of problems:

- **Commands cannot reference the aggregate they intend to create.** A `PlaceOrder`
  command cannot carry the `order_id` because the ID doesn't exist yet. The handler
  must create the aggregate, persist it, extract the generated ID, and return it.
  The caller is left waiting.
- **API responses are coupled to the database round-trip.** The client submits a
  POST request but cannot know the resource URL until the server persists the
  record and returns the generated ID. This blocks optimistic UI patterns and
  forces synchronous, tightly-coupled request flows.
- **Idempotent creation is impossible without the identity.** If the client retries
  a create request (network timeout, user double-click), the system has no way to
  detect the duplicate. Each retry generates a new auto-increment ID, producing
  duplicate records. The check-then-act pattern (`does this order already exist?`)
  requires knowing the identity upfront.
- **Events raised during creation cannot carry a stable identity.** An
  `OrderPlaced` event should contain the `order_id`, but if identity is
  database-assigned, the event is raised before the ID is known -- or the event
  must be patched after persistence, complicating the flow.
- **Distributed systems require central coordination.** Auto-increment IDs depend
  on a single database sequence. In a distributed architecture with multiple
  nodes, services, or event-sourced aggregates, this becomes a bottleneck or a
  single point of failure.

These problems all stem from the same root cause: **deferring identity generation
to the persistence layer**.

---

## The Pattern

Generate the aggregate's identity **at the point of creation** -- or even earlier,
at the system boundary where the intent originates.

```
Traditional flow:
  Client → API → Handler → Create aggregate → Persist → Get ID → Return ID
                                                  ↑
                                          Identity assigned here
                                          (too late)

Early identity flow:
  Client → Generate ID → API (with ID) → Handler → Create aggregate → Persist
    ↑
    Identity assigned here
    (as early as possible)
```

The key insight from Domain-Driven Design is that **identity is intrinsic to an
entity, not a side effect of storage**. An entity is defined by its identity. It
should have that identity from the moment it comes into existence -- not from the
moment it is persisted.

---

## Why This Matters in DDD

### Identity Is Foundational

In DDD, entities and aggregates are distinguished from value objects by one
defining characteristic: **identity**. Two `Order` instances with the same
attributes but different identities are different orders. Two with different
attributes but the same identity are the same order at different points in time.

If identity is foundational, it should be present from birth. An aggregate without
an identity is incomplete -- it cannot participate in domain operations, cannot be
referenced by commands or events, and cannot enforce invariants that depend on
knowing "which one" it is.

### Aggregates Are Consistency Boundaries

An aggregate is the boundary within which invariants are guaranteed. Commands
target a specific aggregate instance by identity. Events reference the aggregate
that changed by identity. Repositories load and persist by identity.

When identity is deferred to the database, there is a gap between the aggregate's
creation and its ability to participate in these operations. Early identity
generation closes this gap entirely.

### Commands Carry Intent and Context

A well-designed command carries everything the handler needs, including the
identity of the aggregate being acted upon. For creation commands, this means the
caller -- not the handler, and not the database -- decides the identity:

```python
# The command carries the identity of the aggregate it will create.
# The caller generates this identity before submitting the command.
PlaceOrder(
    order_id="ord-a1b2c3d4",
    customer_id="cust-789",
    items=[...],
)
```

This makes the command self-contained. The handler doesn't need to generate an ID,
and it can use the same `order_id` in every event it raises, every repository
call it makes, and every response it returns.

### Events Record Facts with Stable References

Domain events are immutable facts. Once raised, they become part of the system's
history. Every downstream consumer -- event handlers, projectors, sagas -- relies
on the identities embedded in these events to correlate, route, and process.

When identity is generated early, events carry stable, meaningful references from
the start:

```python
# The event references the same order_id that the command carried.
# Downstream handlers can immediately correlate this event.
OrderPlaced(
    order_id="ord-a1b2c3d4",
    customer_id="cust-789",
    total=149.99,
)
```

---

## How Protean Supports Early Identity

Protean's identity system is designed around the principle that identities should
be generated close to the point of element creation, without relying on external
infrastructure like databases.

### Automatic Identity Generation at Construction

When you create an aggregate or entity instance, Protean generates its identity
immediately -- at construction time, not at persistence time:

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier()
    total: Float()


# Identity is assigned the moment the object is created
order = Order(customer_id="cust-789", total=149.99)
print(order.order_id)  # '9cf4ddc4-2919-4021-bd1a-c8083b5fdda7'
```

The `Auto` field generates a UUID immediately. No database round-trip, no
sequence query, no central coordinator. The aggregate has its identity from
the moment it exists.

If no identity field is explicitly declared, Protean automatically adds an `Auto`
field named `id`:

```python
@domain.aggregate
class Order:
    customer_id: Identifier()
    total: Float()

order = Order(customer_id="cust-789", total=149.99)
print(order.id)  # Auto-generated UUID
```

### Caller-Supplied Identities

When the caller already has an identity -- because it was generated at the client,
at the API layer, or carried in a command -- it can be supplied directly:

```python
# The caller provides the identity explicitly
order = Order(
    order_id="ord-a1b2c3d4",
    customer_id="cust-789",
    total=149.99,
)
print(order.order_id)  # 'ord-a1b2c3d4'
```

The `Auto` field accepts explicit values. When a value is provided, it is used
as-is. When omitted, a value is auto-generated. This means the same aggregate
definition supports both caller-supplied and framework-generated identities.

### Identity Strategies and Types

Protean's identity system is configurable at two levels: **domain-wide defaults**
and **per-field overrides**.

**Domain-level configuration** (in `domain.toml`):

```toml
identity_strategy = "uuid"    # "uuid" (default) or "function"
identity_type = "string"      # "string" (default), "integer", or "uuid"
```

UUIDs are the default and recommended strategy because they can be generated
anywhere -- in the client, in the API layer, in the command handler -- without
coordination. This is precisely what makes early identity generation possible.

**Per-field override** for aggregates with special requirements:

```python
import time

def gen_epoch_id():
    return int(time.time() * 1000)


@domain.aggregate
class Measurement:
    measurement_id: Auto(
        identifier=True,
        identity_strategy="function",
        identity_function=gen_epoch_id,
        identity_type="integer",
    )
    value: Float()
```

### The Identifier Field on Commands

Commands use the `Identifier` field to carry aggregate identities. Unlike `Auto`,
`Identifier` does not auto-generate values -- the caller must supply them:

```python
@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    items: List()
    total: Float()
```

This design reinforces the pattern: the identity originates at the caller and
flows through the command into the aggregate.

---

## Applying the Pattern

### At the API Boundary

The most common place to generate identities early is the API layer. When a
client sends a creation request, the API endpoint generates (or accepts) the
identity before constructing the command:

```python
import uuid

from fastapi import FastAPI

app = FastAPI()


@app.post("/orders")
async def create_order(request: CreateOrderRequest):
    # Option 1: Accept the identity from the client
    order_id = request.order_id

    # Option 2: Generate at the API layer if not provided
    if not order_id:
        order_id = str(uuid.uuid4())

    domain.process(
        PlaceOrder(
            order_id=order_id,
            customer_id=request.customer_id,
            items=request.items,
            total=request.total,
        )
    )

    # The API can return the identity immediately,
    # without waiting for persistence to complete.
    return {"order_id": order_id, "status": "accepted"}
```

The response includes the `order_id` immediately. If the command is processed
asynchronously, the client already knows the identity and can use it to poll
for status, navigate to the resource, or issue follow-up commands.

### At the Client

For the earliest possible identity generation, the client itself creates the ID:

```
Frontend (browser/mobile):
  1. Generate UUID: "ord-a1b2c3d4-..."
  2. POST /orders { order_id: "ord-a1b2c3d4-...", items: [...] }
  3. Immediately navigate to /orders/ord-a1b2c3d4-...
  4. Display optimistic UI while the server processes

Server:
  1. Receive request with order_id already set
  2. Construct and process PlaceOrder command
  3. Aggregate created with the client-provided identity
```

This enables optimistic UI patterns: the client doesn't wait for the server to
confirm creation before showing the new resource. The UUID guarantees uniqueness
without server coordination.

### First Creation vs. Subsequent Commands

Early identity generation applies specifically to the **creation** command -- the
first command that brings an aggregate into existence. After creation, every
subsequent command naturally carries the identity because you need to know
*which* aggregate to act on:

```python
# Creation: identity generated at the caller
order_id = str(uuid.uuid4())
domain.process(PlaceOrder(order_id=order_id, items=[...]))

# Subsequent commands: identity is already known
domain.process(AddItemToOrder(order_id=order_id, product_id="prod-1", quantity=2))
domain.process(ConfirmOrder(order_id=order_id))
domain.process(ShipOrder(order_id=order_id, tracking_number="TRK-456"))
```

The pattern ensures there is never a moment when the caller lacks the identity
needed to interact with the aggregate.

---

## Enabling Idempotent Creation

Early identity generation is the foundation for idempotent creation commands.
Without it, there is no reliable way to detect whether a create request is a
duplicate.

### The Check-Then-Act Pattern

When the creation command carries the aggregate's identity, the handler can
check whether the aggregate already exists:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)

        # If the order already exists, this is a duplicate command
        existing = repo.get(command.order_id)
        if existing:
            return  # Idempotent: no-op on duplicate

        order = Order(
            order_id=command.order_id,
            items=command.items,
            total=command.total,
        )
        repo.add(order)
```

This pattern is simple and effective. It works without any additional
infrastructure (no Redis, no idempotency keys) and provides handler-level
safety even when framework-level deduplication is unavailable.

For stronger guarantees, combine early identity generation with Protean's
framework-level idempotency keys. See the
[Command Idempotency](command-idempotency.md) pattern for the full treatment.

### Why Database-Generated IDs Break Idempotency

Consider the same handler without early identity:

```python
# Anti-pattern: identity generated by the database
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    # No order_id in the command -- the database will assign one
    order = Order(items=command.items, total=command.total)
    repo.add(order)  # Database generates the ID on insert
```

If this command is delivered twice (network retry, broker redelivery), the handler
creates two separate orders with two different database-assigned IDs. There is
no way to detect the duplicate because each execution looks like a fresh creation.

---

## Choosing the Right Identity Source

| Scenario | Generate Identity At | Rationale |
|----------|---------------------|-----------|
| Standard API creation | API endpoint | Simplest; identity available for immediate response |
| Optimistic UI | Client (browser/mobile) | Client navigates to the resource before server confirms |
| Async command processing | API endpoint or client | Caller needs the identity to correlate the eventual result |
| Saga-initiated creation | Saga/process manager | The saga tracks the identity for compensating actions |
| Event-sourced aggregates | Client or API endpoint | The event stream needs a stable identity from the first event |
| Internal service-to-service | Calling service | The caller tracks the identity for correlation across services |
| Batch/import processing | Import script | Each record gets an identity before the batch begins |

In every case, the principle is the same: **whoever originates the intent generates
the identity**.

---

## When Not to Use This Pattern

Early identity generation is the default recommendation, but there are situations
where it may not apply:

- **Natural identities from the domain**: When the domain itself provides a
  unique identifier -- ISBN for books, email for user accounts, SSN for tax
  records -- you don't need to generate a synthetic identity. Use the
  `identifier=True` flag on the natural key field:

  ```python
  @domain.aggregate
  class Book:
      isbn: String(max_length=13, identifier=True)
      title: String(max_length=200, required=True)
  ```

  The creation command carries this natural identity (`isbn`) from the caller
  naturally, so the pattern's benefits still apply -- just without the UUID
  generation step.

- **Auto-increment requirements from external systems**: Some integrations
  require sequential numeric IDs (invoice numbers, receipt numbers). Use the
  `increment` option on the `Auto` field for these, understanding that identity
  generation is deferred to the database:

  ```python
  @domain.aggregate
  class Invoice:
      invoice_number: Auto(identifier=True, increment=True)
      # ...
  ```

  Even here, consider using a UUID as the internal aggregate identity and
  treating the sequential number as a separate domain attribute assigned during
  a specific workflow step.

---

## Summary

| Aspect | Database-Generated ID | Early Identity |
|--------|----------------------|----------------|
| When assigned | At persistence time | At creation time (or earlier) |
| Who decides | The database | The caller (client, API, saga) |
| Available in commands | No | Yes |
| Available in events | After persistence | Immediately |
| Supports idempotent creation | No | Yes (check-then-act) |
| Supports async processing | Poorly (caller must wait) | Well (caller has the ID immediately) |
| Supports optimistic UI | No | Yes |
| Distributed-friendly | No (central sequence) | Yes (UUIDs need no coordination) |
| Protean default | No | **Yes** (Auto field with UUID) |

The pattern is simple: **generate identities at the origin of intent, not at the
point of storage**. Protean's `Auto` field with UUID generation makes this the
default behavior. Commands carry the identity. Events reference it. Handlers use
it. The entire flow is simpler, more resilient, and naturally idempotent.
