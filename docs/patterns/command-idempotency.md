# Command Idempotency

## The Problem

In a DDD/CQRS system, commands express an intention to change state. In
distributed systems, the same intention can arrive more than once:

- **Network retries**: A client times out waiting for a response and
  retransmits the request, even though the original was processed successfully.
- **Broker redelivery**: A message broker delivers a command to a handler, but
  the handler crashes before acknowledging it. The broker redelivers.
- **Subscription replay**: The server restarts and the event store subscription
  resumes from a position slightly behind where processing actually reached.
- **User behavior**: A user double-clicks a submit button, or refreshes a page
  that triggers a POST.
- **Saga retries**: A process manager retries a compensating command after a
  transient failure in a downstream service.

In all of these cases, the system receives what is logically the *same command*
multiple times. Without idempotency, each delivery produces additional state
changes, duplicate orders, double charges, extra emails.

**Command idempotency** means that processing the same command more than once
produces the same observable effect as processing it exactly once. The system
arrives at the same state regardless of how many times the command is delivered.

---

## Idempotency Keys

An idempotency key is a unique token that identifies a specific **request**,
not a specific data shape or entity. This distinction is critical.

Consider two calls that look identical:

```python
# fragment
# First call: user adds 3 units of product X
domain.process(AddItemToCart(cart_id="c-1", product_id="X", quantity=3))

# Second call: user intentionally adds 3 more units
domain.process(AddItemToCart(cart_id="c-1", product_id="X", quantity=3))
```

These have the same payload, the same entity identifier, but they are
**two different requests**. The user genuinely wants 6 units total. A system
that deduplicates based on the command's data would silently swallow the second
request.

Now consider a retry of the same request:

```python
# fragment
# First attempt: network timeout, client didn't get the response
domain.process(AddItemToCart(cart_id="c-1", product_id="X", quantity=3))

# Retry of the SAME attempt: client re-sends because it didn't get a response
domain.process(AddItemToCart(cart_id="c-1", product_id="X", quantity=3))
```

Same payload, same entity, and now they are truly the **same request**. The
system should process it only once.

The payload alone cannot distinguish these scenarios. Only the caller knows
whether a submission is a retry or a new intent. This is why the idempotency
key must come from the caller.

### Protean's Design: Caller-Provided Keys

Protean follows the model established by Stripe and other well-designed APIs:
the idempotency key is a **header-level field provided by the caller**, not
derived from the command payload.

```python
# fragment
# Each request gets a unique idempotency key from the API layer.
# Retries of the same request reuse the same key.
domain.process(
    AddItemToCart(cart_id="c-1", product_id="X", quantity=3),
    idempotency_key="req-abc-123",
)
```

The key is stored in the command's metadata headers
(`command._metadata.headers.idempotency_key`), not in the command's payload
fields. This keeps the command's domain data clean. The idempotency key is
infrastructure, not business data.

**When no key is provided**, `domain.process()` treats every call as a unique
request. No submission-level deduplication occurs. This is deliberate:
auto-deriving keys from command data creates false positives that silently
break legitimate operations.

### Where Keys Come From

In practice, idempotency keys originate at the system boundary, the API layer,
the message consumer, or the saga coordinator:

```python
# fragment
from fastapi import Header


# In a FastAPI endpoint
@app.post("/carts/{cart_id}/items")
async def add_item(
    cart_id: str,
    request: AddItemRequest,
    # FastAPI reads the client's Idempotency-Key header into this argument.
    # The API layer can also generate one key per request.
    idempotency_key: str | None = Header(default=None),
):
    result = domain.process(
        AddItemToCart(
            cart_id=cart_id,
            product_id=request.product_id,
            quantity=request.quantity,
        ),
        idempotency_key=idempotency_key,
    )
    return {"status": "accepted", "position": result}
```

```python
# fragment
# In a saga / process manager
@handle(PaymentConfirmed)
def on_payment_confirmed(self, event: PaymentConfirmed):
    # Use a deterministic key derived from the triggering event
    # so that retries of the same event produce the same key.
    current_domain.process(
        ShipOrder(order_id=event.order_id),
        idempotency_key=f"ship-for-payment-{event._metadata.headers.id}",
    )
```

---

## Protean's Approach: Three-Layer Idempotency

Protean addresses command idempotency through three independent, complementary
layers. Each layer provides value on its own. Together they form defense in
depth.

```
Layer 3: Handler-Level Idempotency
         Developer patterns for business-level safety

Layer 2: Subscription-Level Deduplication
         Redis-backed check before async handler dispatch

Layer 1: Submission-Level Deduplication
         Redis-backed check in domain.process()
```

### Layer 1: Submission-Level Deduplication

When a caller provides an idempotency key, `domain.process()` checks a
Redis-backed idempotency cache before doing any work.

#### How It Works

```
domain.process(command, idempotency_key="req-123")
    │
    ▼
┌─────────────────────────────┐
│ Check Redis:                │
│ idempotency:req-123 exists? │
└──────────┬──────────────────┘
           │
     ┌─────┴─────┐
     │           │
   Found      Not found
   (success)     │
     │           ▼
     │    ┌──────────────┐
     │    │ Append to    │
     │    │ event store  │
     │    └──────┬───────┘
     │           │
     │           ▼
     │    ┌──────────────┐
     │    │ Process      │
     │    │ (sync/async) │
     │    └──────┬───────┘
     │           │
     │     ┌─────┴─────┐
     │     │           │
     │   Success    Failure
     │     │           │
     │     ▼           ▼
     │   Cache in    Allow retry
     │   Redis       (no cache entry
     │   with TTL    or short-TTL
     ▼               error entry)
  Return
  cached result
```

1. **Cache hit (status: success)**: Return the cached result immediately.
   For sync commands, this is the handler's return value. For async commands,
   this is the event store position. The caller sees exactly the same
   response as the original submission.
   The store keeps the result as JSON, so a sync handler called with an
   idempotency key must return a JSON-serializable value, such as an
   identifier or a count, and not an aggregate.

2. **Cache miss or error entry**: Proceed normally, enrich the command, append
   to event store, process (sync or async), and cache the result on success.

3. **Processing failure**: The command is in the event store but processing
   failed. The Redis entry is either absent or marked as error. The caller
   receives the exception and can safely retry with the same idempotency key.
   The retry goes through from the beginning.

#### Duplicate Behavior

By default, duplicate submissions are **silently acknowledged**, the caller
receives the same result as the first submission. This is critical for retry
safety: a client retrying a failed network request should not get an error
because the first attempt actually succeeded.

When explicit feedback is needed, callers can opt into raising an exception:

```python
# fragment
from protean.exceptions import DuplicateCommandError

# Default: silent acknowledgment (retry-safe)
result = domain.process(
    AddItemToCart(cart_id="c-1", product_id="X", quantity=3),
    idempotency_key="req-abc",
)

# Retry with same key: returns the same result silently
result_again = domain.process(
    AddItemToCart(cart_id="c-1", product_id="X", quantity=3),
    idempotency_key="req-abc",
)
assert result == result_again

# Explicit duplicate detection when the caller needs to know
try:
    domain.process(
        AddItemToCart(cart_id="c-1", product_id="X", quantity=3),
        idempotency_key="req-abc",
        raise_on_duplicate=True,
    )
except DuplicateCommandError as exc:
    # exc carries the original result for inspection
    original_result = exc.original_result
```

#### Without an Idempotency Key

When no key is provided, Layer 1 is bypassed entirely. Every call to
`domain.process()` appends to the event store and proceeds with handling. This
is the appropriate behavior for internal framework use (e.g., saga-generated
commands where the caller manages idempotency at a higher level) or for
commands where handler-level patterns provide sufficient protection.

### Layer 2: Subscription-Level Deduplication

The Protean server engine processes commands asynchronously through event store
subscriptions. Each subscription tracks its read position in the stream so it
knows where to resume after a restart.

Position tracking alone is not sufficient. If the server processes a command
but crashes before persisting the updated position, the command will be
redelivered on restart.

Layer 2 closes this gap by consulting the same Redis idempotency cache that
Layer 1 writes to. When the subscription picks up a command for processing:

1. If the command carries an idempotency key, check Redis.
2. If found with status `success`, skip processing and advance the position.
3. If not found, process the message via the handler.
4. On successful processing, write the result to Redis (just as Layer 1
   would), then advance the position.

For commands **without** idempotency keys, Layer 2 relies on position tracking
alone, the existing behavior. The subscription advances past messages it has
already seen based on its stored position.

#### What This Protects Against

- Server crash between handler execution and position persistence.
- Position update interval gaps (position is written periodically, not after
  every single message).
- Any scenario where the subscription replays messages that were already
  successfully processed.

### Layer 3: Handler-Level Idempotency

Layers 1 and 2 provide framework-level deduplication for commands that carry
idempotency keys. Layer 3 is about making the handler logic itself resilient
to duplicates. This matters in several situations:

- Commands submitted without idempotency keys (Layer 1 is bypassed).
- A fresh deployment or Redis data loss (Layers 1 and 2 have no history).
- Defense-in-depth: even with framework dedup, a well-designed handler should
  not produce corrupt state if called twice.

Handler-level idempotency falls into two categories: operations that are
**naturally idempotent** and those that require **explicit protection**.

---

## Developer Patterns

### Natural Idempotency: Set-Based Operations

Commands that overwrite state rather than accumulate it are inherently
idempotent. "Set the email to X" produces the same result whether executed once
or ten times.

```python
--8<-- "patterns/command-idempotency/002.py:update_email"
```

This is the simplest and most common pattern. If you can design your commands
as set-based operations, you get idempotency for free.

**More examples of naturally idempotent commands:**

- `UpdateAddress`: Replaces the address
- `SetPreference`: Overwrites a preference value
- `AssignRole`: Assigns a role (assigning the same role twice is a no-op)
- `RenameProduct`: Replaces the product name

### Create Operations: Check-Then-Act

Commands that create new aggregates can use existence checks:

```python
--8<-- "patterns/command-idempotency/003.py:place_order"
```

This pattern relies on the command carrying the aggregate's identity (the
`order_id`), which is a best practice in Protean: generate identities early,
ideally at the client.

### Additive Operations: Track Processed Commands

Commands that add items, increment counters, or accumulate state need
explicit deduplication. Processing them twice would produce incorrect state.

When using idempotency keys (the recommended approach), the framework handles
this at Layers 1 and 2. But as defense-in-depth, or when keys aren't
available, the handler can track processed commands on the aggregate:

```python
--8<-- "patterns/command-idempotency/004.py:add_item"
```

The `processed_commands` field on the aggregate serves as a bounded set of
recently processed command keys. For aggregates with high command volume,
this set can be pruned periodically (keeping only the last N entries or
entries within a time window).

### Event-Sourced Aggregates: Expected Version Alone Does Not Stop Duplicates

Event-sourced aggregates in Protean use optimistic concurrency. A handler
loads the aggregate at some version, raises new events, and adds it back to the
repository. When the unit of work commits, the event store checks that the
aggregate's stream is still at the version the handler loaded. If another copy
of the command committed in between, the versions differ and the commit raises
`ExpectedVersionError`.

```python
--8<-- "patterns/command-idempotency/005.py:bank_account"
```

The version check alone does not stop a duplicate. When two copies run at the
same time, both load the same version, the first commits, and the second
fails its commit. A command handler then retries the second copy, because
[version conflict auto-retry](../guides/server/error-handling.md#version-conflict-auto-retry)
is on by default (`version_retry`, 3 retries). The retry loads the newer
version, the check passes, and the deposit is applied a second time. A copy
that arrives after the first one has committed takes the same path without
any conflict. For both cases, pair the aggregate with an idempotency key
(Layers 1 and 2), or track processed command keys on the aggregate as in the
additive pattern above.

The conflict surfaces when the unit of work commits, after the handler method
returns. A `try`/`except ExpectedVersionError` inside the handler never sees it.
The error says only that another write came first, not that it was the same
command. Swallowing it would also drop a different command that happened to
collide, so leave conflicts to the version retry. The error reaches the caller
only when the retries run out or `version_retry` is turned off.

### Cross-Aggregate Commands

Commands that affect multiple aggregates through events are handled by a key
principle: **each aggregate is independently responsible for its own
idempotency**.

The command handler modifies only the primary aggregate. Downstream aggregates
are modified through event handlers, each in its own transaction.

Layer 2 does not cover those event handlers. It checks the idempotency key, and
events do not carry the key of the command that raised them. An event
subscription relies on its stored position alone, so a redelivered event runs
the handler again. Make the event handler idempotent itself, as described in
[Idempotent Event Handlers](idempotent-event-handlers.md).

```python
--8<-- "patterns/command-idempotency/006.py:transfer"
```

### External Side Effects

External side effects (sending emails, calling payment APIs, posting to
third-party services) cannot be made idempotent by the framework alone. The
developer must handle these explicitly.

#### Pattern: Status Flag

Track whether the side effect has already occurred:

```python
# fragment
@handle(SendWelcomeEmail)
def send_welcome(self, command: SendWelcomeEmail):
    repo = current_domain.repository_for(User)
    user = repo.get(command.user_id)

    if user.welcome_email_sent:
        return  # Side effect already occurred

    email_service.send_welcome(user.email)

    user.welcome_email_sent = True
    repo.add(user)
```

#### Pattern: Pass-Through Idempotency Key

Many external APIs support idempotency keys natively (Stripe, payment
processors, notification services). Pass the command's idempotency key
through:

```python
# fragment
@handle(ChargeCard)
def charge_card(self, command: ChargeCard):
    stripe.PaymentIntent.create(
        amount=command.amount,
        currency="usd",
        idempotency_key=command._metadata.headers.idempotency_key,
    )
```

This makes retries safe end-to-end. The same idempotency key that protects
the command at Protean's layer also protects the external API call. If the
charge already went through, Stripe returns the existing result instead of
charging again.

#### Pattern: Outbox for Side Effects

For side effects that must happen exactly once and survive crashes, use the
outbox pattern. Instead of performing the side effect directly in the handler,
raise an event. A separate processor picks it up and executes it with retry
and deduplication:

```python
# fragment
@handle(SendWelcomeEmail)
def send_welcome(self, command: SendWelcomeEmail):
    repo = current_domain.repository_for(User)
    user = repo.get(command.user_id)

    # Raise an event instead of calling the email service directly.
    # The event goes through the outbox, ensuring at-least-once delivery
    # with deduplication at the broker level.
    user.raise_(WelcomeEmailRequested(
        user_id=user.user_id,
        email=user.email,
    ))
    repo.add(user)
```

---

## What Happens on Failure

A critical edge case: the command is appended to the event store, but
processing fails. What should happen on retry?

### Synchronous Processing

The caller submitted a command with an idempotency key and
`asynchronous=False`. The command was stored in the event store, but the
handler threw an exception. The caller receives the error.

On retry (same idempotency key):

- Redis has no `success` entry for this key (it was never cached, or it was
  cached as `error` with a short TTL that has expired).
- The framework treats this as a fresh submission: appends to the event store
  again and re-invokes the handler.
- If the handler succeeds this time, the result is cached in Redis and
  returned.

The duplicate command in the event store is harmless. Both copies are marked
as processed synchronously, and the subscription skips commands that were
already handled inline.

### Asynchronous Processing

The command was stored in the event store and a position was returned. The
subscription picks it up, but the handler fails.

- The subscription advances its position past the failed message (to avoid
  blocking subsequent messages).
- The subscription's retry mechanism (configurable retries with backoff) will
  re-attempt the message.
- If the handler eventually succeeds, the idempotency key is cached in Redis.
- If all retries are exhausted, the message is logged for manual intervention.

If the caller retries with the same idempotency key before the subscription
succeeds:

- Redis has no `success` entry, so Layer 1 allows the submission.
- A second copy of the command enters the event store.
- The subscription processes whichever copy it encounters first. The second
  copy is deduplicated via the Redis cache (Layer 2).

---

## Choosing the Right Pattern

| Scenario | Recommended Approach |
|----------|---------------------|
| Any command from an API endpoint | Provide an idempotency key at the API layer. Framework handles dedup. |
| Overwriting a field (set email) | Naturally idempotent. Key optional but recommended. |
| Creating a new aggregate | Key + check-then-act in handler as defense-in-depth. |
| Adding items / incrementing counters | **Key required.** Framework dedup is essential; additive ops are not naturally safe. |
| Event-sourced aggregate mutations | **Key required.** The version retry re-runs a conflicting copy, so expected version alone does not stop a duplicate. |
| Commands from sagas / process managers | Derive key from the triggering event's ID for deterministic dedup. |
| Sending emails, calling external APIs | Key + pass-through to external service's own idempotency mechanism. |
| Exactly-once side effects surviving crashes | Key + outbox pattern with events. |

### When to Provide Idempotency Keys

The short answer: **always, for commands that originate from system boundaries
(API endpoints, message consumers, saga coordinators).**

Idempotency keys are the only reliable way to distinguish a retry from a new
request. Without a key, the framework cannot help with submission-level or
subscription-level deduplication. Handler-level patterns still work, but they
require more effort from the developer and are less reliable for additive
operations.

The only case where omitting a key is reasonable is for purely internal
commands where the calling code already guarantees exactly-once delivery, or
where the command is naturally idempotent (set-based operations).

---

## How the Layers Work Together

Consider a `PlaceOrder` command flowing through the system:

**API Layer**: The client sends a POST to `/orders` with header
`Idempotency-Key: req-abc`. The endpoint calls
`domain.process(PlaceOrder(...), idempotency_key="req-abc")`.

**Layer 1 (Submission)**: `domain.process()` checks Redis for
`idempotency:req-abc`. Not found. It enriches the command (setting
`_metadata.headers.idempotency_key = "req-abc"`), appends to the event store,
and processes synchronously. The handler creates the order and returns the
order's identifier. The framework caches
`{status: "success", result: "ord-42"}` in Redis with a 24-hour TTL and
returns the identifier to the caller.

**Client retries**: The client didn't receive the response (network issue) and
retries with the same `Idempotency-Key: req-abc`. `domain.process()` checks
Redis, finds the `success` entry, and returns the cached identifier immediately.
No event store write, no handler invocation. The client sees the same response
as if the first call had succeeded normally.

**Layer 2 (Subscription)**: For async commands, the subscription picks up the
command from the event store. It reads the idempotency key from the command's
metadata headers and checks Redis. If found with `success`, it skips
processing and advances position. If not found (e.g., command was submitted
without processing), it invokes the handler and caches the result on success.

**Layer 3 (Handler)**: Even if Redis were empty (fresh deployment, data loss),
the handler's check-then-act logic (does `ord-42` already exist?) provides the
final safety net. The order is created exactly once.

Each layer catches what the others miss. No single layer needs to be perfect.

---

## Configuration

Idempotency behavior is configured in `domain.toml`:

```toml
[idempotency]
# Redis connection for the idempotency cache.
# Unset by default. Without it, Layers 1 and 2 do nothing.
redis_url = "${REDIS_URL}"

# Time-to-live for idempotency records in seconds.
# After this period, the same key can be reused.
# Default: 86400 (24 hours)
ttl = 86400

# Time-to-live for error records in seconds.
# Short TTL allows retries after transient failures.
# Default: 60
error_ttl = 60
```

The same settings can be made in code before the domain initializes. Here the
Redis URL comes from the `REDIS_URL` environment variable, and the store stays
off when the variable is unset:

```python
--8<-- "patterns/command-idempotency/001.py:config"
```

---

!!! tip "Related reading"
    **Concepts:**

    - [Commands](../concepts/building-blocks/commands.md): Commands as intent to change state.
    - [Command Handlers](../concepts/building-blocks/command-handlers.md): Processing commands and persisting state.

    **Guides:**

    - [Commands](../guides/change-state/commands.md): Defining commands, idempotency keys, and processing modes.
    - [Command Handlers](../guides/change-state/command-handlers.md): Handler definition, workflow, and idempotency handling.
