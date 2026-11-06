# Creating Identities Early

## The problem

In most systems the database assigns the identity. A row gets an auto-increment
integer when you save it. Until the save completes, neither the aggregate nor
the caller has an identity.

Waiting on the save for an identity causes five problems:

- **A command cannot reference the aggregate it creates.** A `PlaceOrder` command
  cannot carry an `order_id`, because no `order_id` exists yet. The command
  handler has to create the order, persist it, read back the generated ID, and
  return it. The caller waits on all of it.
- **The API response waits on the database.** A client POSTs an order, and the
  server cannot return the resource URL until it has written the row. Because
  of that wait, you cannot use optimistic UI. The request also has to stay
  synchronous.
- **A retry cannot be spotted by identity.** When the client retries after a
  timeout, or the user double-clicks, the request carries no order ID that the
  handler can check. Each attempt writes another row with another ID. A
  separate idempotency key can still catch the repeat; the aggregate's own
  identity cannot.
- **Events raised during creation carry no stable reference.** `OrderPlaced`
  should carry the `order_id`, but the event is raised before the database has
  assigned one. Either the event is raised without the `order_id`, or you patch
  the event after the write.
- **Auto-increment depends on a single sequence.** Distribute the work across
  nodes, services, or event-sourced aggregates and that sequence becomes a
  bottleneck and a single point of failure.

All five follow from one decision: letting the storage layer assign the identity.

---

## The pattern

Give the aggregate its identity when you create it. Better still, give it one
earlier, at the caller that starts the intent.

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

Domain-Driven Design treats identity as part of what an entity **is**. Storage
does not give an entity its identity. An entity is defined by its identity, so
it should have one from the moment it exists.

---

## Why it matters

### An aggregate without an identity is incomplete

Identity is what separates entities and aggregates from value objects. Two
`Order` instances with the same fields but different identities are two different
orders. Two with different fields but the same identity are one order at two
points in time.

An aggregate without an identity cannot be told apart from another aggregate or
followed from one point in time to the next. Nothing can address the aggregate,
and no command or event can reference it. It also cannot enforce any rule that
depends on its identity.

### Commands, events and repositories are keyed on identity

An aggregate is the boundary that holds your invariants. Commands target one
instance by identity. Events say which aggregate changed by identity.
Repositories load and save by identity.

Defer the identity to the database, and the aggregate exists for a time before
any command, event or repository can refer to it. Generate the identity early,
and the aggregate has it from the start.

### A command should carry everything the handler needs

That includes the identity of the aggregate it acts on. For a creation command,
the caller decides it, not the handler and not the database:

```python
# fragment
# The command carries the identity of the aggregate it will create.
# The caller generates this identity before submitting the command.
PlaceOrder(
    order_id="ord-a1b2c3d4",
    customer_id="cust-789",
    items=[...],
)
```

Now the command carries everything the handler needs, including the identity.
The handler reuses that one `order_id` in its events, its repository calls and
its return value.

### Events are facts, and facts need stable references

Domain events are immutable. Once raised, they are part of your history. Every
event handler, projector, and process manager downstream uses the identities
inside the events to correlate and route.

Generate the identity early and the identities in your events are stable from
the first event:

```python
# fragment
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

Protean generates an identity when you construct the element, without asking
any database.

### You get an identity at construction

Create an aggregate or entity and it has its identity immediately:

```python
--8<-- "patterns/creating-identities-early/001.py:aggregate"
```

`Auto` generates a UUID at construction time. No database round-trip, no sequence
query, no central coordinator.
The aggregate reads the identity settings from the domain, so construct it
inside `domain.domain_context()`.

Declare no identity field and Protean adds an `Auto` field called `id`:

```python
--8<-- "patterns/creating-identities-early/002.py:default-id"
```

### You can supply your own

When you already have an identity from the client, the API layer or a command,
pass it straight through:

```python
--8<-- "patterns/creating-identities-early/001.py:supplied"
```

`Auto` takes an explicit value and uses it as given. Leave it out and you get a
generated one. The same aggregate definition covers both.

### Configure the identity strategy and type

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
--8<-- "patterns/creating-identities-early/003.py:function"
```

### `Identifier` on commands

Commands carry aggregate identities in `Identifier` fields. A plain
`Identifier` field generates nothing, so the caller supplies the value. Marked
`identifier=True`, it falls back to the domain's configured identity generator
when the caller leaves it out, a UUID by default. So, whenever the caller's
identity has to be preserved, pass it in:

```python
--8<-- "patterns/creating-identities-early/001.py:command"
```

With `Identifier` fields, the caller creates the identity, and the command
handler passes it from the command to the aggregate.

---

## Applying the pattern

### Generate the identity at the API boundary

The API layer is the usual place. When a creation request arrives, take the
identity from the client or make one. Then build the command:

```python
--8<-- "patterns/creating-identities-early/001.py:api"
```

You return the `order_id` right away. If the command runs asynchronously the
client already knows the identity and can poll on it, navigate to it, or send
follow-up commands with it.

### Generate the identity at the client

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

The client shows the new order without waiting for the server to confirm it.
The UUID is unique whoever makes it, so the client and the server do not have
to coordinate.

### Pass the identity in every command after creation

Generating the identity early applies to the **creation** command, the one that
brings the aggregate into existence. Every later command carries the identity
anyway, because each one names its target aggregate:

```python
# fragment
# Creation: identity generated at the caller
order_id = str(uuid.uuid4())
domain.process(PlaceOrder(order_id=order_id, items=[...]))

# Subsequent commands: identity is already known
domain.process(AddItemToOrder(order_id=order_id, product_id="prod-1", quantity=2))
domain.process(ConfirmOrder(order_id=order_id))
domain.process(ShipOrder(order_id=order_id, tracking_number="TRK-456"))
```

The caller never holds a reference that it cannot use.

---

## Make creation idempotent

An early identity gives the handler a stable key for spotting duplicates.
Without it the handler has no aggregate ID to look up, so a repeat has to be
caught some other way, with a caller-supplied idempotency key.

### Check, then act

The command carries the identity, so the handler can look first:

```python
--8<-- "patterns/creating-identities-early/001.py:handler"
```

`get_or_none()` returns `None` only when the order is missing, so any other
repository failure still surfaces. This catches a retry that arrives after the
first write is visible, and it needs no Redis and no extra infrastructure. It
is not deduplication on its own: two deliveries running at the same time can
both read a miss before either write completes.

Protean's idempotency keys do not prevent this race condition either.
`domain.process()` checks the key before handling and records the result after,
so two deliveries running together can both read a miss. They protect a retry
only after Protean has recorded the result. For simultaneous deliveries you
need something atomic. A unique constraint on the identity column is the
simplest: the second insert fails, and the retry that follows finds the row.
The [Command Idempotency](command-idempotency.md) pattern covers keys in full.

### Why database IDs break it

Take the same handler without an identity in the command:

```python
# fragment
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

In every row of the table, the caller that starts the intent makes the
identity.

---

## When to do something else

Start here by default, but two cases call for something different.

**The domain already has a key.** Books have an ISBN, tax records have an SSN.
Do not invent a second identity; mark the real one:

```python
--8<-- "patterns/creating-identities-early/004.py:natural-key"
```

The creation command carries the `isbn` from the caller, so you keep the benefits
and skip the UUID. Only take this route for a key that never changes. An email
or a username reads like an identity until someone updates it, and then every
command, event, and reference holding the old value points at nothing.

**An external system needs a sequence.** Invoice and receipt numbers often have
to run in order. Use `increment` on the `Auto` field, and accept that the
database now assigns the identity:

```python
--8<-- "patterns/creating-identities-early/005.py:sequence"
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
