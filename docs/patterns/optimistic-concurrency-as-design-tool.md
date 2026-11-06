# Use Optimistic Concurrency as a Design Tool

## The Problem

Protean tracks aggregate versions automatically. Every aggregate carries a
`_version` field. When the `UnitOfWork` commits, the framework compares the
version in the database with the loaded version. If another transaction
modified the aggregate in the meantime, the commit raises
`ExpectedVersionError`.

Most teams treat `ExpectedVersionError` as a generic infrastructure failure and
answer it with "something went wrong, try again":

```python
# fragment
from protean.exceptions import ExpectedVersionError


@domain.application_service(part_of=Order)
class OrderService(BaseApplicationService):

    @use_case
    def update_order(self, order_id: str, data: dict) -> Order:
        repo = current_domain.repository_for(Order)
        order = repo.get(order_id)

        order.update_details(**data)
        repo.add(order)
        return order
```

When two users edit the same order concurrently, one of them gets an
`ExpectedVersionError`. The API layer catches it and returns a generic
HTTP 409:

```python
# fragment
# In the API layer
try:
    order_service.update_order(order_id, data)
except ExpectedVersionError:
    return {"error": "Conflict. Please try again."}, 409
```

This is correct mechanically, the version check prevented data corruption. But
as an architecture choice, the generic handler is weak. The user sees "try
again" and no explanation of the cause or the lost change. The user also cannot
tell whether trying again will even work.

Worse, the same generic handler is used whether the conflict is:

- Two users changing display settings at the same time (harmless; either value
  is fine)
- Two users booking the same concert seat (critical; one of them must be told
  the seat is taken)
- Two users adding items to a shared shopping cart (mergeable; both additions
  can coexist)

These are fundamentally different situations that deserve fundamentally
different responses. A version conflict is not a failure. It is a
**signal** that tells you something meaningful about how your domain is
being used under contention.

---

## The Pattern

Stop treating `ExpectedVersionError` as a generic infrastructure error.
Instead, classify version conflicts by their **business meaning** and choose a
deliberate response for each category.

There are three categories:

### 1. Last writer wins

The conflict does not matter. Either value is acceptable. Your code reloads the
aggregate, applies the change again, and persists it.

**This category fits** user preferences, display settings, notification
toggles, and profile descriptions.

### 2. Conflict means a real problem

The conflict signals that the operation is no longer valid. Reload the
aggregate and let its precondition raise a domain-specific exception that
tells the user exactly what happened.

**This category fits** seat reservations, inventory allocation, one-time coupon
redemption, and unique username registration.

### 3. Merge if possible

The conflict does not invalidate the operation. You still cannot blindly
overwrite the newer version. Your code loads the latest version and checks
whether the specific change still makes sense. It then applies the change or
rejects it with a clear explanation.

**This category fits** adding items to a shared cart, appending tags to a
document, and collaborative editing of independent fields.

For **event-sourced aggregates**, version conflicts matter even more. The event
store uses `_version` to prevent contradictory event sequences from being
appended. An `ExpectedVersionError` from the event store is the system working
correctly. It prevents an impossible history from being recorded. Silencing it
with a blind retry can introduce logical contradictions in the event stream.

---

## Applying the Pattern

### Category 1: Last writer wins (retry loop)

When concurrent changes are harmless and either outcome is acceptable, your
code retries on the latest version: it catches the version conflict, reloads
the aggregate, reapplies the operation, and commits.

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/001.py:aggregate"
```

The application service implements a retry loop. The operation is safe to retry
after a version conflict because each change is independent and idempotent.
Setting the theme to "dark" produces the same result regardless of the number
of runs. Each attempt runs in its own `UnitOfWork`. A conflict with a
concurrent write can surface when the unit of work commits. For that reason,
the `except` clause is outside the `with` block. Call the service outside any
other unit of work. Inside one, each attempt joins the outer unit of work, and
the conflict surfaces at the outer commit with no retry.

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/001.py:service"
```

!!! note "Why not retry everything?"
    A retry loop is appropriate here because `update_theme` is a **set-based
    operation**. The result depends only on the input, not on the previous
    state. For additive operations (incrementing a counter, appending to a
    list), blind retries can produce incorrect results. Always verify that the
    operation is safe to repeat before adding a retry loop.

### Category 2: Conflict means a real problem (business exception)

Sometimes a version conflict means the operation is no longer valid. In that
case, the caller should get a domain-specific exception instead of a generic
"try again." The aggregate's own precondition gives that answer. It raises
`SeatAlreadyTaken` when the seat is no longer available.

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/002.py:aggregate"
```

The command handler does not catch `ExpectedVersionError`. Depending on the
adapter and the aggregate, the conflict surfaces inside `repo.add` or at the
commit of the handler's unit of work. That commit happens after the handler
method has returned. An `except` clause in the handler either never runs or
stops the retry that follows. Instead, the framework catches the conflict and
runs the handler again in a fresh unit of work. On the reloaded aggregate,
`reserve()` finds that the seat is reserved and raises `SeatAlreadyTaken`. Two
customers might try to reserve the same seat simultaneously. One succeeds, and
the other learns that the seat is taken instead of seeing a vague "conflict".

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/002.py:handler"
```

The API layer can now give the customer a meaningful response:

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/002.py:api"
```

!!! warning "The precondition must be complete"
    The framework's retry is safe here only because `reserve()` checks the
    seat's status on the reloaded aggregate. If the precondition has a gap, the
    retry succeeds and double-books the seat. The conflict *is* the answer:
    another customer reserved the seat first, and the precondition turns that
    conflict into `SeatAlreadyTaken`. If you turn auto-retry off, the caller
    gets the raw `ExpectedVersionError` and must translate it.

### Category 3: Merge if possible (conditional retry)

When the operation might still be valid despite the conflict, your code reloads
the aggregate and rechecks the specific change against the latest version. It
then applies the change or rejects it with a clear explanation.

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/003.py:aggregate"
```

The application service reloads and checks whether the add-item operation
is still valid on the latest version. Two team members adding different
items simultaneously should both succeed. Two members adding the same item
need the quantities merged correctly.

```python
--8<-- "patterns/optimistic-concurrency-as-design-tool/003.py:service"
```

The application service differs from a simple retry loop (category 1) in one
way: **re-evaluation**. On each attempt, the service loads the latest version
and checks the preconditions again. If another team member's concurrent change
pushed the cart past `max_items`, the service rejects the operation with a
clear reason instead of retrying it blindly.

---

## Framework auto-retry and when it is not enough

Protean automatically retries `ExpectedVersionError` at the `@handle` wrapper
level. When a handler raises a version conflict, the framework catches it and
waits with exponential backoff. The framework then re-executes the handler in a
**fresh `UnitOfWork`**, and the handler re-reads the aggregate at the latest
version. This happens transparently, before the error reaches the subscription
retry pipeline. By default, the framework retries up to 3 times with 50 ms
initial backoff (350 ms worst case).

!!! warning "The retry budget scales with contention, not with load"
    Under optimistic concurrency, only **one** writer can commit per version
    of an aggregate. When `k` writers race the *same* aggregate at the *same*
    moment, they serialise: the first commits immediately, the second needs one
    retry, the third needs two, and the `k`-th may need up to `k-1` retries.
    The retries a writer needs therefore scale with the number of **simultaneous
    contenders on one aggregate**, not with overall throughput.

    So the default of 3 is tuned for ordinary contention (a handful of writers
    touching the same aggregate at once). It is deliberately *not* enough for a
    **hot aggregate** (a flash-sale SKU, a shared counter, one popular
    account) where many writers converge on a single item. There, some writers
    will exhaust the 3 retries and surface `ExpectedVersionError` even though the
    operation would eventually have succeeded. Exponential backoff spreads
    contenders out and usually keeps you well under the worst case, but it cannot
    remove the fundamental one-winner-per-round limit.

    Raising `max_retries` gives writers more attempts but does not reduce the
    contention. The durable fix is to **remove the hotspot**: serialise writes
    to the aggregate (single-writer / queue), split it into [smaller
    aggregates](design-small-aggregates.md) so unrelated changes stop
    colliding, or use an atomic conditional write for pure counters. A higher
    retry budget fits one case: a brief, bounded burst on one aggregate that
    you expect and cannot avoid. In that case, raise `max_retries`. Bounded
    retries are a feature: they fail fast instead of livelocking under
    sustained contention.

This auto-retry is the right behavior for **category 1** (last writer wins)
conflicts. The handler re-reads the aggregate and reapplies the change. Which
is safe because either value is acceptable. In many cases, you do not need to
write manual retry loops for category 1 scenarios because the framework handles
it.

Auto-retry also serves categories 2 and 3, but only when the handler
re-checks its preconditions against the reloaded aggregate:

- **Category 2** (conflict means a real problem): The retry reloads the
  aggregate, and the aggregate's precondition raises a domain-specific
  exception (e.g., `SeatAlreadyTaken`). The handler does not need to
  catch anything. Without that precondition, the retry would apply the
  change again, which is exactly what category 2 conflicts should avoid.

- **For category 3** (merge if possible), the handler must reload the aggregate
  and re-evaluate preconditions. The framework re-runs the handler in a fresh
  `UnitOfWork`, so your handler loads the latest aggregate state. Your handler
  code must still implement the merge logic. Simple re-execution works only
  when the operation is idempotent.

!!! note "Why a handler should not catch `ExpectedVersionError` itself"
    Depending on the adapter and the aggregate, a conflict surfaces inside
    `repo.add` or at the commit of the handler's unit of work. That commit
    happens after the method returns. A `try`/`except` inside the handler
    either never sees the conflict or catches it and stops the framework's
    retry. Put the decision in the aggregate's preconditions, which run again
    on every retry. Some code needs its own retry loop, like the application
    services in categories 1 and 3. That code opens a `UnitOfWork` for each
    attempt and catches the error outside the `with` block.

For auto-retry configuration, see
[Version conflict auto-retry](../guides/server/error-handling.md#retry-version-conflicts-automatically).
To disable auto-retry entirely, set `enabled = false` in
`[server.version_retry]`.

---

## How do the adapters keep the version check atomic?

The pattern above assumes that `ExpectedVersionError` is raised reliably
whenever two writers race on the same aggregate. Whether that assumption holds
depends on the repository's adapter. Since the 5.1 hardening work (the fixes
that closed the race between the version check and the write), every
first-party adapter checks the expected version **in the same atomic operation
as the write**. There is no window in which two writers can both observe the
same version and both commit.

| Adapter | Mechanism |
|---------|-----------|
| SQLAlchemy repository | Conditional `UPDATE ... WHERE _version = :expected` with rowcount verification inside the same transaction |
| Memory repository | `threading.Lock` serialises the version check and the write |
| Elasticsearch repository | Native `if_seq_no` and `if_primary_term` on the index operation |
| Memory event store | `threading.Lock` guards the `write()` call |
| MessageDB event store | Stored-procedure API enforces expected version inside PostgreSQL |

Earlier versions of the SQLAlchemy and memory adapters used a
SELECT-then-UPDATE pattern with a time-of-check to time-of-use window. Two
concurrent handlers could both pass the `SELECT _version` check and both issue
their `UPDATE`. The slower writer would then silently overwrite the faster one
without raising `ExpectedVersionError`. That window is now closed. With any
first-party adapter, two concurrent writers on the same aggregate always
produce one success and one `ExpectedVersionError`.

**What this means for the pattern.** Category 2 handlers (seat reservations,
inventory allocation) can rely on the version check alone to detect that
another writer changed the aggregate first. Before 5.1, a handler sometimes
needed a hand-written defensive `SELECT FOR UPDATE`. The adapter's conditional
write is now sufficient.

**What this means for custom adapters.** A third-party repository or
event store implementation must preserve this invariant: the version
check and the write must be one atomic step. Implement it using the
database's native conditional-write primitive (row-level lock plus
`WHERE _version = :expected`, `compare-and-swap`, or equivalent). A
SELECT-then-UPDATE shortcut will reintroduce the race and silently
discard writes.

---

## Anti-Patterns

### Catching every conflict in one generic handler

The most common anti-pattern: catching `ExpectedVersionError` at the API
boundary and returning a generic message for all conflict types.

```python
# fragment
# Anti-pattern: one handler for all conflicts
@app.exception_handler(ExpectedVersionError)
async def handle_version_conflict(request, exc):
    return JSONResponse(
        status_code=409,
        content={"error": "Conflict detected. Please try again."},
    )
```

This tells the user nothing useful. Was their seat taken? Did their cart
change? Is their data lost? The caller cannot distinguish between a harmless
race condition and a fundamental problem.

### Retrying every conflict blindly

Wrapping every operation in a retry loop without considering the semantics.

```python
# fragment
# Anti-pattern: retry without considering the operation type
def with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except ExpectedVersionError:
            if attempt == max_retries - 1:
                raise
```

This is dangerous for category 2 conflicts (seat booking, inventory
reservation). Retrying a failed reservation might succeed on a different
version of the aggregate, producing a double booking. It is also wrong for
additive operations unless the handler explicitly re-evaluates preconditions
on the reloaded aggregate.

!!! note "How this differs from framework auto-retry"
    Protean's built-in auto-retry at the `@handle` level **also** retries
    blindly, which is correct for category 1 conflicts (the vast majority). For
    categories 2 and 3, the retry is safe only because each attempt reloads
    the aggregate and runs its preconditions again. Keep those checks in the
    aggregate, as `reserve()` does in category 2.

### Ignoring version conflicts entirely

Suppressing the error and returning success.

```python
# fragment
# Anti-pattern: swallowing the error
def adjust_inventory(product_id, delta):
    try:
        with UnitOfWork():
            repo = current_domain.repository_for(Inventory)
            inv = repo.get(product_id)
            inv.adjust_quantity(delta)
            repo.add(inv)
    except ExpectedVersionError:
        pass  # "It'll sort itself out"
```

The code drops the inventory adjustment, and no later step recovers it. The
caller believes the operation succeeded. Downstream systems may act on that
assumption. Inventory counts will drift from reality.

### Building oversized aggregates that increase contention

When an aggregate is too large, unrelated changes cause spurious version
conflicts. Suppose `Order` contains the customer profile, shipping address,
payment details, and line items in a single aggregate. Updating the shipping
address and adding a line item will then conflict, even though the two changes
are unrelated.

```python
# fragment
# Anti-pattern: large aggregate creates false conflicts
@domain.aggregate
class Order(BaseAggregate):
    order_id: Auto(identifier=True)
    customer_name: String()          # Changes independently
    customer_email: String()         # Changes independently
    shipping_address: Text()         # Changes independently
    items = HasMany(OrderItem)       # Changes independently
    payment_status: String()         # Changes independently
    notes: Text()                    # Changes independently
```

Every field shares the same `_version`. Any change to any field increments the
version and conflicts with any concurrent change to any other field. The fix is
smaller aggregates: each aggregate's version then protects only the data that
genuinely must be consistent. See [Design Small
Aggregates](design-small-aggregates.md).

---

## Summary

| Conflict category | Business meaning | Response | Example |
|-------------------|-----------------|----------|---------|
| **Last writer wins** | Either value is fine | Reload, reapply, commit | User preferences, display settings |
| **Real problem** | Operation is no longer valid | Raise a domain-specific exception | Seat reservation, inventory allocation |
| **Merge if possible** | Operation may still be valid | Reload, re-evaluate preconditions, retry or reject | Shared cart, collaborative tagging |

| Principle | Practice |
|-----------|----------|
| Version conflicts are signals, not errors | Classify each conflict by business meaning |
| Small aggregates reduce contention | Fewer fields per aggregate means fewer false conflicts |
| One aggregate per transaction | Do not expand the conflict surface across aggregates |
| Event-sourced versions prevent contradictions | Never silently swallow `ExpectedVersionError` on event streams |
| Handlers own the conflict strategy | The handler (or application service) decides: retry, reject, or merge |

---

!!! tip "Related reading"
    **Patterns:**

    - [Design Small Aggregates](design-small-aggregates.md): Smaller aggregates mean fewer version conflicts.
    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md): Single aggregate per handler reduces contention.
    - [Command Idempotency](command-idempotency.md): Idempotency keys prevent duplicate operations.

    **Guides:**

    - [Unit of Work](../guides/change-state/unit-of-work.md): Transaction management and version tracking.
    - [Persist Aggregates](../guides/change-state/persist-aggregates.md): Repository persistence patterns.
    - [Error Handling](../guides/server/error-handling.md#retry-version-conflicts-automatically): Framework auto-retry configuration for version conflicts.
