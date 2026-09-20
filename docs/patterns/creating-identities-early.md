# Creating Identities Early

## The problem

In most systems the database assigns the identity. A row gets an auto-increment
integer when you save it, so until the save completes the aggregate has no
identity and neither does the caller.

That delay causes five problems:

- **A command cannot reference the aggregate it creates.** A `PlaceOrder` command
  cannot carry an `order_id`, because no `order_id` exists yet. The handler has to
  create the order, persist it, read back the generated ID, and return it. The
  caller waits on all of it.
- **The API response waits on the database.** A client POSTs an order, and the
  server cannot return the resource URL until it has written the row. That rules
  out optimistic UI and keeps the request synchronous.
- **A retry cannot be spotted by identity.** If the client retries after a
  timeout, or the user double-clicks, the request carries no order ID to check
  against, and each attempt writes another row with another ID. A separate
  idempotency key can still catch the repeat; the aggregate's own identity
  cannot.
- **Events raised during creation carry no stable reference.** `OrderPlaced`
  should carry the `order_id`, but the event is raised before the database has
  assigned one. Either the event goes out incomplete, or you patch it after the
  write.
- **Auto-increment depends on a single sequence.** Distribute the work across
  nodes, services, or event-sourced aggregates and that sequence becomes a
  bottleneck and a single point of failure.

All five follow from one decision: letting the storage layer assign the identity.

---

## The pattern

Give the aggregate its identity when you create it, or earlier still, wherever
the intent starts.

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

Domain-Driven Design treats identity as part of what an entity **is**, not as
something storage does to it. An entity is defined by its identity, so it should
have one from the moment it exists.

---

## Why it matters

### An aggregate without an identity is incomplete

Identity is what separates entities and aggregates from value objects. Two
`Order` instances with the same fields but different identities are two different
orders. Two with different fields but the same identity are one order at two
points in time.

An aggregate without an identity can take part in none of this. Nothing can address it, no
command or event can reference it, and it cannot enforce any rule that depends on
knowing which one it is.

### Everything else is keyed on it

An aggregate is the boundary that holds your invariants. Commands target one
instance by identity. Events say which aggregate changed by identity.
Repositories load and save by identity.

Defer the identity to the database and you open a window where the aggregate
exists but can do none of that. Generating it early closes the window.

### A command should carry everything the handler needs

That includes the identity of the aggregate it acts on. For a creation command,
the caller decides it, not the handler and not the database:

```python
# The command carries the identity of the aggregate it will create.
# The caller generates this identity before submitting the command.
PlaceOrder(
    order_id="ord-a1b2c3d4",
    customer_id="cust-789",
    items=[...],
)
```

Now the command stands on its own. The handler reuses that one `order_id` in
every event it raises, every repository call it makes, and whatever it returns.

### Events are facts, and facts need stable references

Domain events are immutable. Once raised they are part of your history, and every
event handler, projector, and process manager downstream uses the identities
inside them to correlate and route.

Generate the identity early and those references are stable from the first event:

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

## What Protean gives you

Protean generates identities close to where the element is created, without
asking any database.

### You get an identity at construction

Create an aggregate or entity and it has its identity immediately:

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

`Auto` generates a UUID at construction time. No database round-trip, no sequence
query, no central coordinator.

Declare no identity field and Protean adds an `Auto` field called `id`:

```python
@domain.aggregate
class Order:
    customer_id: Identifier()
    total: Float()

order = Order(customer_id="cust-789", total=149.99)
print(order.id)  # Auto-generated UUID
```

### You can supply your own

When you already have an identity, because the client made it, or the API layer
did, or a command carried it in, pass it straight through:

```python
# The caller provides the identity explicitly
order = Order(
    order_id="ord-a1b2c3d4",
    customer_id="cust-789",
    total=149.99,
)
print(order.order_id)  # 'ord-a1b2c3d4'
```

`Auto` takes an explicit value and uses it as given. Leave it out and you get a
generated one. The same aggregate definition covers both.

### Strategies and types

You configure identity in two places: a default for the domain, and an override
per field.

For the domain, in `domain.toml`:

```toml
identity_strategy = "uuid"    # "uuid" (default) or "function"
identity_type = "string"      # "string" (default), "integer", or "uuid"
```

UUIDs are the default because anyone can generate one anywhere, in the client, in
the API layer, in the handler, without checking with anything else. That is what
makes early identity possible at all.

For one field with its own needs:

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

### `Identifier` on commands

Commands carry aggregate identities in `Identifier` fields. A plain `Identifier`
field generates nothing, so the caller supplies the value. Marked
`identifier=True`, it falls back to a generated UUID when the caller leaves it
out, so pass the caller's identity in whenever it has to be preserved:

```python
@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    items: List()
    total: Float()
```

The field type says what the pattern says: the identity starts at the caller and
flows through the command into the aggregate.

---

## Putting it to work

### At the API boundary

The API layer is the usual place. When a creation request arrives, take the
identity from the client or make one, then build the command:

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

You return the `order_id` right away. If the command runs asynchronously the
client already knows the identity and can poll on it, navigate to it, or send
follow-up commands with it.

### At the client

Earlier still: let the client make the ID.

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

The client shows the new order without waiting for the server to confirm it. The
UUID is unique whoever makes it, so nothing has to coordinate.

### Creation, then everything after

This applies to the **creation** command, the one that brings the aggregate into
existence. Every later command carries the identity anyway, because you have to
say which aggregate you mean:

```python
# Creation: identity generated at the caller
order_id = str(uuid.uuid4())
domain.process(PlaceOrder(order_id=order_id, items=[...]))

# Subsequent commands: identity is already known
domain.process(AddItemToOrder(order_id=order_id, product_id="prod-1", quantity=2))
domain.process(ConfirmOrder(order_id=order_id))
domain.process(ShipOrder(order_id=order_id, tracking_number="TRK-456"))
```

There is never a point where the caller is holding a reference it cannot use.

---

## Idempotent creation

An early identity gives the handler a stable key for spotting duplicates.
Without it the handler has no aggregate ID to look up, so a repeat has to be
caught some other way, with a caller-supplied idempotency key.

### Check, then act

The command carries the identity, so the handler can look first:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)

        # If the order already exists, this is a duplicate command
        existing = repo.get_or_none(command.order_id)
        if existing:
            return  # Idempotent: no-op on duplicate

        order = Order(
            order_id=command.order_id,
            items=command.items,
            total=command.total,
        )
        repo.add(order)
```

`get_or_none()` returns `None` only when the order is missing, so any other
repository failure still surfaces. This catches a retry that arrives after the
first write is visible, and it needs no Redis and no extra infrastructure. It is
not deduplication on its own: two deliveries running at the same time can both
read a miss before either write lands.

To close that gap, pair it with Protean's idempotency keys. The
[Command Idempotency](command-idempotency.md) pattern covers that in full.

### Why database IDs break it

Take the same handler without an identity in the command:

```python
# Anti-pattern: identity generated by the database
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    # No order_id in the command -- the database will assign one
    order = Order(items=command.items, total=command.total)
    repo.add(order)  # Database generates the ID on insert
```

Deliver that command twice, through a network retry or a broker redelivery, and
you get two orders with two IDs. Both executions look like a first attempt, so
nothing can tell them apart.

---

## Where to generate it

| Scenario | Generate Identity At | Rationale |
|----------|---------------------|-----------|
| Standard API creation | API endpoint | Simplest; identity available for immediate response |
| Optimistic UI | Client (browser/mobile) | Client navigates to the resource before server confirms |
| Async command processing | API endpoint or client | Caller needs the identity to correlate the eventual result |
| Saga-initiated creation | Saga/process manager | The saga tracks the identity for compensating actions |
| Event-sourced aggregates | Client or API endpoint | The event stream needs a stable identity from the first event |
| Internal service-to-service | Calling service | The caller tracks the identity for correlation across services |
| Batch/import processing | Import script | Each record gets an identity before the batch begins |

The rule behind every row: whoever starts the intent makes the identity.

---

## When to do something else

Start here by default, but two cases call for something different.

**The domain already has a key.** Books have an ISBN, accounts have an email, tax
records have an SSN. Do not invent a second identity; mark the real one:

```python
@domain.aggregate
class Book:
    isbn: String(max_length=13, identifier=True)
    title: String(max_length=200, required=True)
```

The creation command carries the `isbn` from the caller, so you keep the benefits
and skip the UUID.

**Something outside needs a sequence.** Invoice and receipt numbers often have to
run in order. Use `increment` on the `Auto` field, knowing you have handed
identity back to the database:

```python
@domain.aggregate
class Invoice:
    invoice_number: Auto(identifier=True, increment=True)
    # ...
```

Even then, consider giving the aggregate a UUID of its own and treating the
sequential number as a domain attribute you assign at the right step.

---

## Summary

| Aspect | Database-Generated ID | Early Identity |
|--------|----------------------|----------------|
| When assigned | At persistence time | At creation time (or earlier) |
| Who decides | The database | The caller (client, API, saga) |
| Available in commands | No | Yes |
| Available in events | After persistence | Immediately |
| Duplicate detection by aggregate ID | No (needs an idempotency key) | Yes (check-then-act) |
| Async processing | Works, but the caller cannot name the result yet | Works, and the caller has the ID immediately |
| Supports optimistic UI | No | Yes |
| Distributed-friendly | No (central sequence) | Yes (UUIDs need no coordination) |
| Protean default | No | **Yes** (Auto field with UUID) |

Generate the identity where the intent originates, at the caller, and pass it
in. Protean's `Auto` field takes that value as given, and generates a UUID when
the aggregate is constructed without one. The command carries the identity, the
events reference it, and the handler uses it to spot duplicates. Add an
idempotency key where retries have to be safe.

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md): Aggregate identity and versioning.

    **Guides:**

    - [Identity](../reference/domain-elements/identity.md): Identity strategies, types, and configuration.
    - [Fields](../reference/fields/index.md): The Auto and Identifier field types.
