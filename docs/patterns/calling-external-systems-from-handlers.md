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

The `@handle` decorator wraps every handler method in a Unit of Work. Since the
decision that a Unit of Work is a real transaction
([ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)), that Unit of
Work is one real database transaction. The transaction opens at the first
repository access and stays open until the method returns. So the `httpx.post`
runs inside the transaction. While the call waits on the partner, it holds the
row locks and the pooled connection acquired by `repo.get` and `repo.add`.

Two things go wrong from there. A slow partner holds locks for the length of
the call. Under load, the connection pool runs out of connections while every
handler waits on the network. And version-conflict (OCC) retry re-runs the
whole method body, so a retry re-posts to the partner. The webhook fires twice
for one order.

---

## The Pattern

A handler method either persists or calls an external system. Not both.

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

Sometimes the call has to follow the write, or needs a value that the write
produces. In that case, the persisting method raises an event and the calling
method handles that event:

```python
--8<-- "patterns/calling-external-systems-from-handlers/003.py:chain"
```

Protean writes `OrderConfirmed` to the
[outbox](../concepts/async-processing/outbox.md) inside the confirming
transaction and publishes it after that transaction commits. As a result,
`notify_partner` runs after the write is durable. The value it needs travels on
the event. `confirmed_at` is a `datetime`, and a `datetime` is not JSON. So
`notify_partner` sends `confirmed_at` as an ISO 8601 string.

With sync event processing, `notify_partner` runs in the caller's thread right
after the confirming commit. If the partner call fails, the caller gets a
`TransactionError`. Even then, the confirmed order stays saved.

---

## How Protean Supports This

**The Unit of Work is lazy.** A handler method that reaches no repository runs
no transaction and holds no pooled connection. So you can rely on the "no
persistence means no transaction" half of the persist-or-call-out rule. See
[When the transaction actually
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
when a method calls out after a repository access. By that point the
transaction is already open. The check is advisory: a handler that needs the
call's result sometimes has to do both.

---

## Applying the Pattern

### Syncing many facets from one external snapshot

The costly shape is a multi-facet sync, where a facet is one part of an
aggregate's state, such as its contact details. In a multi-facet sync, one
external fetch produces a snapshot, several facets apply it to the same
aggregate, and some facets depend on what an earlier facet wrote. A billing
provider sync is a good example. One `Subscriber` aggregate holds contact
details, a plan, and the feature flags the plan unlocks, and all three come
from the provider. A `ProfileSnapshot` holds one fetched copy of the provider's
data. The `Subscriber` and `ProfileSnapshot` aggregates look like this:

```python
--8<-- "patterns/calling-external-systems-from-handlers/001.py:aggregates"
```

**Fetch once, persist the snapshot, raise one event.** One handler fetches the
snapshot from the provider, then persists it. The fetch comes before any
repository access, so it runs before the transaction opens.

```python
--8<-- "patterns/calling-external-systems-from-handlers/001.py:fetch"
```

Because the fetch comes before the persist, the call holds no lock. `protean
check` does not flag the fetch, because the check fires only on a call made
after a repository access. A retry re-runs the fetch, a safe repeat for a read.

`ProfileFetch` is part of `Subscriber`, yet it adds a `ProfileSnapshot`. It
creates a new record and changes no existing one, so no other writer competes
for it. To change an existing aggregate of another kind, issue a command to it,
as the next step does.

The handler persists the snapshot with its own identity, so the payload stays
out of the event. The step that applies the facets then loads the snapshot by
id rather than carrying it on the event or fetching it again. A fat event would
put the whole payload into the event store forever. A re-fetch per facet would
turn one call into several.

**Apply every facet in one command.** `ProfileSnapshotStored` belongs to
`ProfileSnapshot`, so the event handler is part of `ProfileSnapshot`. The
handler issues one `ApplyProfileSnapshot` command, which is part of
`Subscriber`. Subscriber's command handler applies every facet:

```python
--8<-- "patterns/calling-external-systems-from-handlers/001.py:sync"
```

The facets run in one method, in the order the code gives: contact, then plan,
then flags. The feature flags depend on the plan tier, so
`set_flags_for_tier()` reads the tier that `change_plan()` has just set.
Ordinary code sets this order, which is the right way to express an ordering
dependency. All three facets and the snapshot id go into `Subscriber` in one
write.

Events are delivered at least once, so the same `ProfileSnapshotStored` can
arrive twice. `Subscriber` records the ids of the snapshots it has applied.
When the command handler sees one of those ids again, it returns without
changes. The id is saved in the same write as the facets. A retry after that
write commits does nothing. A retry after a failed write applies the snapshot
again in full.

The command handler expects the `Subscriber` to exist already. If it does not,
`repo.get` raises `ObjectNotFoundError`, and the command fails and is retried
like any other failed message.

`subscriber_id` is the command's identifier, so every `ApplyProfileSnapshot`
for one subscriber goes to the same command stream. Even with one command
stream per subscriber, Protean can apply the snapshots out of order. Several
workers can handle commands for the same subscriber at once, and after a
version conflict the retried command can apply an older snapshot over a newer
one. If the order matters, store the provider's sequence number or timestamp on
`Subscriber`. Then skip any snapshot older than the last one applied.

### Recording the result of a call

A notification dispatcher sends a message through a channel. It then records on
the `Notification` whether the send worked. The record step needs the send's
result, so the call has to come first. Here are the `Notification` aggregate
and the `RecordDispatchResult` command, which records the result:

```python
--8<-- "patterns/calling-external-systems-from-handlers/005.py:model"
```

The sending method makes the call and reaches no repository. It hands the write
to the `RecordDispatchResult` command with `asynchronous=True`:

```python
--8<-- "patterns/calling-external-systems-from-handlers/005.py:dispatch"
```

The domain uses sync command processing. The `@handle` decorator opens a Unit
of Work around `send`, so `domain.process` stores the command with that Unit of
Work and returns `None`. The command runs after the Unit of Work commits, in
its own Unit of Work with its own version retry. After a version conflict on
the `Notification`, Protean retries only the record step, so the channel sends
once.

When the record step fails after its last retry, the commit raises
`TransactionError` with the failure as its cause. If more than one command or
event handler failed, the cause is an `ExceptionGroup`. It never raises a
version conflict, so the caller's own version retry does not send again. The
same deferral applies inside a `@use_case` method, a `with UnitOfWork():` block
and an explicit `UnitOfWork.start()`. Outside any Unit of Work,
`domain.process(command, asynchronous=True)` handles the command at once and
returns its result. For the reasons, see the decision that handlers persist or
call out
([ADR-0031](../adr/0031-handlers-persist-or-call-out.md#when-the-call-comes-first-and-the-write-needs-its-result)).

Suppose the process stops after the commit and before the command runs. The
command then stays stored and not handled, the same risk as for events handled
in sync mode. Your domain might list `TransactionError` among the exceptions it
retries as transient. In that case, the retry runs the whole method again and
sends a second message. Leave `TransactionError` off that list.

Under `event_processing = "async"`, the `TransactionError` from a failed record
step also reaches the engine. The engine delivers the `NotificationDispatchStarted`
event again, up to its retry limit, and each delivery sends another message.
Pass the channel an idempotency key, such as the notification's id, so the
channel drops the repeats.

### When the two genuinely cannot be split

Sometimes the write needs the call's result, so the two cannot go in separate
methods. An address validation service returns a normalized address, and the
aggregate stores what the service returned:

```python
--8<-- "patterns/calling-external-systems-from-handlers/004.py:customer"
--8<-- "patterns/calling-external-systems-from-handlers/004.py:normalize"
```

Call first, then persist. The Unit of Work is lazy, so the transaction opens at
`repo.get`. By then the call has already returned, so it holds no lock. One
risk remains: OCC or transient retry re-runs the whole method and re-issues the
call. Pass the remote system's idempotency key so the repeat is harmless.
Protean builds no mechanism for this; the idempotency key is what makes the
retry safe.

Sometimes the call itself needs a value that you can only read from the
aggregate first (a stored token, the current balance). Then the call has to run
between the read and the write, inside the transaction that the read opened.
`protean check` reports that method as HANDLER_PERSISTS_AND_CALLS_OUT. Keep the
call short, pass the idempotency key, and silence the check on that handler
with `suppress_checks`.

---

## Anti-Patterns

### One method that persists then calls out

This is the `confirm_and_notify` method from [The Problem](#the-problem): the
external call sits inside the transaction the write opened, so it holds locks
and a connection while it waits on the partner, and an OCC retry re-posts.
Split the method into `confirm` and `notify_partner`. When the call must follow
the write, chain it to `OrderConfirmed`.

### Issuing one command per facet

It can look tidier to give each facet its own command: `UpdateContact`,
`ChangePlan` and `SetFlags`, all issued by the same event handler. With async
command processing, each command is delivered and processed on its own, in its
own transaction. When `ChangePlan` fails and waits for a retry, `SetFlags` still
runs, reads the old tier, and sets the wrong flags. Each command also loads
`Subscriber` and writes a new version of it, so one sync costs three writes
instead of one.

Keep facets that depend on each other in one command and one command handler
method, where their order is the order of the code.

### Carrying the snapshot on the event or fetching it for each facet

If you pass the fetched snapshot on the event, the event grows large and the
event store keeps the payload permanently. If you re-fetch the snapshot for
each facet, one external call becomes one call per facet. Persist the snapshot
once with its own identity. Load it by id.

---

## When Not to Use / Trade-offs

The one-method form in [When the two genuinely cannot be
split](#when-the-two-genuinely-cannot-be-split) is the exception, for a write
that needs the call's result. That form relies on the remote system's
idempotency key, since a split cannot help.

When you split persistence from external calls, you write more handler methods.
The value one method needs from another then travels on an event. That is the
cost of not holding a transaction open while an external call runs.

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

    - Handlers persist or call out
      ([ADR-0031](../adr/0031-handlers-persist-or-call-out.md)): The decision
      and the options it rejected.
    - [Outbox](../concepts/async-processing/outbox.md): How an event published after commit delivers the value to the next handler.

    **Patterns:**

    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md): The sibling rule for cross-aggregate writes.
    - [Idempotent Event Handlers](idempotent-event-handlers.md): Making a duplicated delivery harmless.
