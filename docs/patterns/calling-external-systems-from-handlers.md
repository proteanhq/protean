# Calling External Systems from Handlers

## The Problem

A handler reacts to `OrderPlaced` by confirming the order and posting to a
partner's webhook. The code reads naturally:

```python
# fragment
@handle(OrderPlaced)
def confirm_and_notify(self, event):
    repo = current_domain.repository_for(Order)
    order = repo.get(event.order_id)        # transaction opens here
    order.confirm()
    repo.add(order)
    httpx.post(PARTNER_URL, json={"order_id": event.order_id})   # holds locks
```

The `@handle` decorator wraps every handler method in a Unit of Work, and since
[ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md) that Unit of Work
is one real database transaction. The transaction opens at the first repository
access and stays open until the method returns. So the `httpx.post` runs inside
the transaction, and while it waits on the partner it holds the row locks and the
pooled connection that `repo.get` and `repo.add` acquired.

Two things go wrong from there. A slow partner holds locks for the length of the
call, and under load the connection pool drains while every handler waits on the
network. And version-conflict (OCC) retry re-runs the whole method body, so a
retry re-posts to the partner. The webhook fires twice for one order.

---

## The Pattern

A handler method either persists or talks to the outside world. Not both.

Split the work into two methods:

- **A persisting method** loads the aggregate, mutates it, persists it, and
  raises an event. It makes no external call.
- **A calling method** makes the external call and reaches no repository. With no
  repository access it runs no transaction and holds no connection, so the call
  costs only wall-clock time.

The examples below use this `Order` aggregate and a `post_to_partner` function
that sends one payload to the partner's webhook:

```python
--8<-- "patterns/calling-external-systems-from-handlers/002.py:model"
```

When the two reactions are independent, they can sit in one handler class as
sibling methods and run in any order:

```python
--8<-- "patterns/calling-external-systems-from-handlers/002.py:siblings"
```

When the call has to follow the write, or needs a value the write produces, the
persisting method raises an event and the calling method handles that event:

```python
--8<-- "patterns/calling-external-systems-from-handlers/003.py:chain"
```

`OrderConfirmed` goes to the [outbox](../concepts/async-processing/outbox.md)
inside the confirming transaction and is published once that transaction commits,
so `notify_partner` runs after the write is durable. The value it needs travels
on the event. `confirmed_at` is a `datetime`, which is not JSON, so
`notify_partner` sends it as an ISO 8601 string.

With sync event processing, `notify_partner` runs in the caller's thread right
after the confirming commit. If the partner call fails, the caller gets a
`TransactionError`, and the confirmed order stays saved.

---

## How Protean Supports This

**The Unit of Work is lazy.** A handler method that reaches no repository runs no
transaction and holds no pooled connection, so the "no persistence means no
transaction" half of the rule is a guarantee you can rely on. See [When the
transaction actually
opens](../guides/change-state/unit-of-work.md#when-the-transaction-actually-opens).

**The outbox delivers the value to the calling method.** The event the persisting
method raises is written to the [outbox](../concepts/async-processing/outbox.md)
in that transaction and published after it commits, so the call runs after the
write is durable and the outbox retries delivery on its own.

**Sibling methods are independent.** Several methods on one handler class react to
the same event, each in its own Unit of Work and in no guaranteed order, and one
that fails does not stop the others. See [Event
Handlers](../guides/consume-state/event-handlers.md#the-handle-decorator).

**A check flags the shape.** `protean check` reports
[HANDLER_PERSISTS_AND_CALLS_OUT](../reference/fitness-functions.md#handler-persists-and-calls-out)
when a method calls out after a repository access, the point at which the
transaction is already open. It is advisory, because a handler that needs the
call's result sometimes has to do both.

---

## Applying the Pattern

### Syncing many facets from one external snapshot

The costly shape is a multi-facet sync: one external fetch produces a snapshot,
several facets apply it to the same aggregate, and some facets depend on what an
earlier facet wrote. A billing provider sync is a good example. One `Subscriber`
aggregate holds contact details, a plan, and the feature flags the plan unlocks,
and all three come from the provider. A `ProfileSnapshot` holds one fetched
copy of the provider's data. The two aggregates look like this:

```python
--8<-- "patterns/calling-external-systems-from-handlers/001.py:aggregates"
```

**Fetch once, persist the snapshot, raise one event.** One handler fetches the
snapshot from the provider, then persists it. The fetch comes before any
repository access, so it runs before the transaction opens.

```python
--8<-- "patterns/calling-external-systems-from-handlers/001.py:fetch"
```

Because the fetch precedes the persist, the call holds no lock, and `protean
check` does not flag it: the rule fires only on a call that comes after a
repository access. A retry re-runs the fetch, a safe repeat for a read.

`ProfileFetch` is part of `Subscriber`, yet it adds a `ProfileSnapshot`. It
creates a new record and changes no existing one, so no other writer competes
for it. To change an existing aggregate of another kind, issue a command to it,
as the next step does.

Persisting the snapshot and giving it an identity keeps the payload out of the
event. The step that applies the facets then loads the snapshot by id rather
than carrying it on the event or fetching it again. A fat event would put the
whole payload into the event store forever, and a re-fetch per facet turns one
call into several.

**Apply every facet in one command.** `ProfileSnapshotStored` belongs to
`ProfileSnapshot`, so the event handler is part of `ProfileSnapshot`. The
handler issues one `ApplyProfileSnapshot` command, which is part of
`Subscriber`, and Subscriber's command handler applies every facet:

```python
--8<-- "patterns/calling-external-systems-from-handlers/001.py:sync"
```

The facets run in one method, in the order the code gives: contact, then plan,
then flags. The feature flags depend on the plan tier, so
`set_flags_for_tier()` reads the tier that `change_plan()` has just set. The
order is ordinary code, which is where an ordering dependency belongs. All three
facets and the snapshot id go into `Subscriber` in one write.

Events are delivered at least once, so the same `ProfileSnapshotStored` can
arrive twice. `Subscriber` records the ids of the snapshots it has applied, and
the command handler returns without changes when it sees one again. The id is
saved in the same write as the facets. A retry after that write commits does
nothing, and a retry after a failed write applies the snapshot again in full.

The command handler expects the `Subscriber` to exist already. If it does not,
`repo.get` raises `ObjectNotFoundError`, and the command fails and is retried
like any other failed message.

`subscriber_id` is the command's identifier, so every `ApplyProfileSnapshot` for
one subscriber goes to the same command stream. That choice of stream does not
make the snapshots apply in order. Several workers can handle commands for the
same subscriber at once, and after a version conflict the retried command can
apply an older snapshot over a newer one. If the order matters, store the
provider's sequence number or timestamp on `Subscriber` and skip a snapshot that
is older than the last one applied.

### When the two genuinely cannot be split

Sometimes the write needs the call's result, so the two cannot go in separate
methods. An address validation service returns a normalized address, and the
aggregate stores what the service returned:

```python
--8<-- "patterns/calling-external-systems-from-handlers/004.py:customer"
--8<-- "patterns/calling-external-systems-from-handlers/004.py:normalize"
```

Call first, then persist. Because the Unit of Work is lazy, the transaction opens
at `repo.get`, after the call has already returned, so the call holds no lock. The
risk that remains is that OCC or transient retry re-runs the whole method and
re-issues the call. Pass the remote system's idempotency key so the repeat is
harmless. Protean builds no mechanism for this; the idempotency key is what makes
the retry safe.

When the call itself needs a value you can only read from the aggregate first (a
stored token, the current balance), the call has to sit between the read and the
write, inside the transaction the read opened. `protean check` reports that method
as HANDLER_PERSISTS_AND_CALLS_OUT. Keep the call short, pass the idempotency key,
and silence the check on that handler with `suppress_checks`.

---

## Anti-Patterns

### One method that persists then calls out

This is the `confirm_and_notify` method from [The Problem](#the-problem): the
external call sits inside the transaction the write opened, so it holds locks and
a connection while it waits on the partner, and an OCC retry re-posts. Split it
into `confirm` and `notify_partner`, and chain the call to `OrderConfirmed` when
it must follow the write.

### One command per facet

It can look tidier to give each facet its own command: `UpdateContact`,
`ChangePlan` and `SetFlags`, all issued by the same event handler. With async
command processing, each command is delivered and processed on its own, in its
own transaction. When `ChangePlan` fails and waits for a retry, `SetFlags` still
runs, reads the old tier, and sets the wrong flags. Each command also loads
`Subscriber` and writes a new version of it, so one sync costs three writes
instead of one.

Keep facets that depend on each other in one command and one command handler
method, where their order is the order of the code.

### A fat event or a re-fetch per facet

Passing the fetched snapshot on the event makes the event large and writes the
payload into the event store permanently. Re-fetching the snapshot for each facet
turns one external call into one per facet. Persist the snapshot once, give it an
identity, and load it by id.

---

## When Not to Use / Trade-offs

The one-method form covered in [When the two genuinely cannot be
split](#when-the-two-genuinely-cannot-be-split) is the exception: when the write
needs the call's result, the split cannot help, so reach for the remote system's
idempotency key.

Splitting persistence from external calls means more handler methods, and the
value one method needs from another travels on an event. That is the cost of not
holding a transaction open while an external call runs.

---

## Summary

| Situation | What to write |
|-----------|---------------|
| Persist and call out, independent | Two sibling methods on one class |
| Call must follow the write, or needs its value | Persisting method raises an event; calling method handles it |
| Many facets of one aggregate from one snapshot | Fetch and persist the snapshot once, raise one event, and have its handler issue one command that applies every facet |
| A facet depends on what an earlier facet wrote | Apply both in the same method, in order |
| The write needs the call's result | One method, plus the remote system's idempotency key |
| Facets that touch different aggregates | One event handler on the event's aggregate issues one command per target aggregate |
| Facets that all mutate one aggregate | One command to that aggregate, never one command per facet |

---

!!! tip "Related reading"
    **Guides:**

    - [Unit of Work](../guides/change-state/unit-of-work.md): When the transaction opens, and why a call-only method holds no connection.
    - [Event Handlers](../guides/consume-state/event-handlers.md): Defining handlers, sibling independence, and subscriptions.

    **Reference:**

    - [HANDLER_PERSISTS_AND_CALLS_OUT](../reference/fitness-functions.md#handler-persists-and-calls-out): The advisory check for a call that follows a repository access.

    **Explanation:**

    - [ADR-0031](../adr/0031-handlers-persist-or-call-out.md): The decision and what was rejected along the way.
    - [Outbox](../concepts/async-processing/outbox.md): How an event published after commit delivers the value to the next handler.

    **Patterns:**

    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md): The sibling rule for cross-aggregate writes.
    - [Idempotent Event Handlers](idempotent-event-handlers.md): Making a duplicated delivery harmless.
