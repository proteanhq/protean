# ADR-0031: A handler method persists or calls out, never both

**Status:** Accepted

> Amended October 2026, see "Siblings are independent in failure" under
> Decision. Amended November 2026, see "No repository access, no
> transaction" under Decision.

**Date:** August 2026

## Context

`@handle` wraps every handler invocation in a `UnitOfWork`
(`src/protean/utils/mixins.py`). A handler cannot turn that wrapping off or
change it. Since the decision that the Unit of Work is a real transaction
(ADR-0027), each Unit of Work is one real database transaction. A handler that
calls an external system therefore holds row locks and a pooled connection for
the length of that call. Version (OCC) and transient retry re-run the whole
handler body, so a retry re-issues the call.

A request came in for `@handle(SomeEvent, unit_of_work=False)`: run the handler
with no wrapping Unit of Work so it can own its own transaction boundaries and
commit sub-units independently. We worked through the cases and found that the
request named a real problem but asked for the wrong fix. Most of what it asked
for either already works or should not be built.

We based the decision on three facts:

1. **The Unit of Work is lazy.** `start()` opens no session. The session, and
   on SQLAlchemy the real `BEGIN`, appears at the first repository access. We
   confirmed this on the memory and SQLite providers. A handler method that
   persists nothing already runs with no transaction, by accident of the
   implementation.

2. **Handler methods are already transactionally independent.** For event
   handlers and projectors, `_dispatch_handlers` loops over every matching
   handler method and each one gets its own `UnitOfWork`. One event handled by
   three methods is already three independent transactions.

3. **They are not independent in failure.** The loop propagates the first
   exception, so it skips the sibling methods that have not run yet.
   `_handlers` is a `defaultdict(set)`, so the set of skipped siblings is
   arbitrary. With three methods where the second fails, one sibling ran and
   one never did.

Spring models this problem as a propagation enum (`REQUIRED`, `REQUIRES_NEW`,
`NOT_SUPPORTED`, `NESTED`). Spring raises an error when a transactional event
listener picks a propagation that cannot work. Axon makes the Unit of Work a
lifecycle with phases, and components register work into a phase. Axon gives
components no way to opt out. Django offers `on_commit()`,
`atomic(durable=True)` and `non_atomic_requests`. Django loses its `on_commit`
callbacks on a crash. NServiceBus is explicit that its outbox covers outgoing
messages only and does not extend to HTTP, email, or the filesystem. Temporal
records a side effect's result in history so replay returns the recorded value
instead of re-executing.

## Decision

**A handler method either persists or calls an external system. Not both.**

Around it:

- **No repository access, no transaction**: When a handler method invocation
  reaches no repository, Protean runs no transaction and holds no connection
  for it. Protean now states the lazy Unit of Work session as a contract.
  Before this decision, the lazy session was an incidental optimization. The
  contract is about the invocation, not about the body: a handler carrying
  `idempotent=True` reads its `(message_id, handler)` marker before the body
  runs, and when the marker store is DB-backed that read is itself a repository
  access, so those invocations open a session before the body.

  *Amended (November 2026): the SQL event store can share the `default`
  database ([ADR-0048](0048-sql-event-store.md)). In that setup, Protean still
  runs a handler method's body with no transaction when the method sends a
  command and reaches no repository. The Unit of Work holds the command until
  the body returns. At commit it opens one transaction on `default`, appends
  the command and commits. The invocation holds a connection only for that
  append. An external call in the body runs outside any transaction. On Message
  DB, and on a SQL event store with its own `database_uri`, the store appends
  the command on its own connection when the handler sends it.*

- **Both in one method**: When a handler needs an external result to compute
  its local write, it does both in one method. The transaction then stays open
  for the length of the call. The mitigation is the remote system's idempotency
  key and keeping the call short. Protean builds no mechanism for this.

- **Protean will report a method that does both**: An advisory diagnostic will
  report each handler method that both persists and calls out. It is advisory.
  The previous point makes that shape legitimate sometimes, and a check that
  fires on correct code is one people learn to ignore. It is suppressible
  through the existing `suppress_checks` option.

- **Siblings are independent in failure**: Fact 3 above (the loop skips sibling
  methods after the first exception) is a defect against the model this ADR
  states. Protean fixes that defect. Among one handler class's methods, two
  failures are excluded from that, for reasons that come from the machinery
  rather than the principle. An `ExpectedVersionError` propagates at once.
  Under asynchronous processing, the conflict fails the whole message and the
  engine redelivers it. Every sibling then runs again. Under synchronous
  processing nothing redelivers, so the methods after the conflict do not run
  for that event. (The conflicting method's own retry runs inside `@handle`,
  and it has already used all its attempts by this point.) A `BaseException`
  that is not an `Exception` also stops dispatch. Only the raised exception
  propagates, so nothing downstream would report the failures already
  collected. On both paths, Protean therefore attaches those failures to the
  raised exception as a note and logs them.

  *Amended (October 2026): across handler classes under synchronous processing,
  Protean collects an `ExpectedVersionError` like any other failure. The
  command's commit then reports it as a `TransactionError` with the conflict as
  its `__cause__`. The only exclusion left across handler classes is a
  `BaseException` that is not an `Exception`. Under the first version of this
  decision, Protean let the conflict stop the drain and reach the commit
  unchanged. As a result, the command's version retry ran the command again
  after its writes were already saved. The retry saved those writes twice. When
  version retry is enabled, `@handle` retries a conflict in an event handler or
  projector through that handler's own retry. A process manager calls its
  methods without that wrapper, so its conflict is not retried.*

- **Process managers are out of scope**: `BaseProcessManager` overrides
  `_handle` and runs its own loop, so it keeps the old skip-on-first-failure
  behavior. A process-manager method drives a state transition, so carrying on
  after one fails has to be reconciled with what the instance's state means
  afterwards. That is a separate decision, not an oversight.

- **Protean does not order handlers for the same event**: When two reactions
  must happen in order, the second reacts to what the first did. So the second
  subscribes to an event the first raises. With an ordering option, you would
  declare that dependency in configuration, and nothing at the call site would
  show it. With an event chain, you write that dependency in the code, where
  correlation and causation IDs already trace it. You can also test each step
  of the chain on its own.

### The shapes this produces

Two reactions to one event, one persisting and one calling out. The two
reactions are independent and run in no particular order. Neither reaction can
cancel the other:

```python
@domain.event_handler(part_of=Order)
class OrderReactions:
    @handle(OrderPlaced)
    def reserve_stock(self, event):
        repo = current_domain.repository_for(Inventory)
        stock = repo.find_by(product_id=event.product_id)
        stock.reserve(event.quantity)
        repo.add(stock)

    @handle(OrderPlaced)
    def notify_partner(self, event):
        # The channel call reaches no repository.
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})
```

Sometimes the call has to follow the write or needs a value the write produces.
In that case the persisting method raises an event, and the calling method
handles that event:

```python
@domain.event_handler(part_of=Order)
class OrderConfirmation:
    @handle(OrderPlaced)
    def confirm(self, event):
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirm()                     # raises OrderConfirmed
        repo.add(order)


@domain.event_handler(part_of=Order)
class PartnerNotifier:
    @handle(OrderConfirmed)
    def notify_partner(self, event):
        httpx.post(
            PARTNER_URL,
            json={"order_id": event.order_id, "confirmed_at": event.confirmed_at},
        )
```

`OrderConfirmed` goes to the outbox inside the confirming transaction, and
Protean publishes it once that transaction commits. So `notify_partner` runs
after the write is durable. The value it needs travels on the event.

Avoid one method that does both. In that method, the external call runs inside
the transaction that the repository access opened:

```python
@handle(OrderPlaced)
def confirm_and_notify(self, event):
    repo = current_domain.repository_for(Order)
    order = repo.get(event.order_id)        # transaction opens here
    order.confirm()
    repo.add(order)
    httpx.post(PARTNER_URL, json={"order_id": event.order_id})   # holds locks
```

#### When the call comes first and the write needs its result

Some flows reverse the order: they make the call, then save what it returned. A
notification dispatcher sends a message through a channel and then records
whether the send worked. The record step needs the send's result, so it cannot
come first. The sending method has no aggregate to raise an event from, so it
cannot pass the result on through an event either.

The sending method calls the channel, then hands the write to a command with
`domain.process(command, asynchronous=True)`:

```python
@domain.event_handler(part_of=Notification)
class NotificationDispatcher:
    @handle(NotificationDispatchStarted)
    def send(self, event):
        # The channel call reaches no repository.
        outcome = channel.send(event.recipient, event.body)
        current_domain.process(
            RecordDispatchResult(
                notification_id=event.notification_id,
                status="SENT" if outcome.ok else "FAILED",
            ),
            asynchronous=True,
        )
```

In a domain with `command_processing = "sync"`, a call to
`domain.process(command, asynchronous=True)` inside an active unit of work
stores the command and returns `None` when the command has a registered
handler. A command with no registered handler still goes to the engine. Protean
handles the command after the caller's unit of work commits, in its own unit of
work with its own version retry. The same applies whoever opened the unit of
work: a handler, a `@use_case` method, a `with UnitOfWork():` block or an
explicit `UnitOfWork.start()`. It applies under both `event_processing`
settings. Sync event processing already runs event handlers this way
(ADR-0016). `asynchronous=True` already means "outside my transaction". Called
outside any unit of work, the same call still handles the command at once and
returns its result.

So when a version conflict occurs on the record step, Protean retries the
record step alone. The send runs once. The record step can still fail, or its
deadline can pass before it runs. In either case, the caller's commit raises
`TransactionError`. It never raises `ExpectedVersionError`, which would make
the caller's own version retry run the send again. A rollback of the caller
means the command never runs.

A `TransactionError` from the record step still reaches whatever runs the
caller. Under `event_processing = "async"`, the engine then delivers the event
again, up to its retry limit, and each delivery sends again. Protean leaves
those repeats to the remote system: pass the channel an idempotency key, and
the remote system drops a repeated send.

Protean stores every command it handles itself, at once or after the commit,
with `asynchronous = False`. The engine's command subscription skips such a
command, so a running engine does not handle it a second time. The cost is the
same one sync events carry: if the process stops after the caller commits and
before the command runs, the stored command is not handled.

With an `idempotency_key`, the command records its outcome when its handler
runs. A repeat call after a success returns the cached result. A repeat call
after a failure stores the command and defers it again.

Two other answers were rejected. A version retry scoped to one step would make
atomicity depend on the order in which the method reaches its repositories. A
"requires new" block, which commits on its own, would be new public API. Such a
block also brings back the nesting questions this ADR avoids.

**No new API is added.** Everything else the request asked for already exists: the
outbox for outbound messages, `idempotent=True` for redelivery, event chains for
sequencing, and separate handler classes for full independence with their own
subscriptions and checkpoints.

The lazy Unit of Work already behaves as the "no repository access, no
transaction" guarantee requires. A regression test will check that behavior so
that a later change cannot break it unnoticed. The advisory diagnostic does not
exist yet. The sibling-skipping defect is fixed for event handler and projector
methods, and for sibling handler classes under synchronous dispatch, so sync
now matches async. In both processing modes, "independent reactions to one fact
are independent in failure" now holds for event handlers and projectors, apart
from the two exclusions under "Siblings are independent in failure". The same
sibling-skipping defect remains at two sites (process managers' own dispatch
loop and broker subscribers) and is tracked separately.

## Consequences

Positive:

- The rule fits in one sentence and is checkable, both by a reader looking at a
  single method and by a static rule.
- Protean's public API does not grow. You do not learn a new flag, phase,
  scope, or journal. You also do not reason about a new interaction with retry,
  idempotency, or nesting.
- Sibling handler methods become genuinely independent once the sibling-skipping
  defect is fixed, matching the model users already have of them.
- This decision leaves the rule that the Unit of Work is a real transaction
  (ADR-0027) unchanged. No Unit of Work nests or commits independently. One
  Unit of Work still maps to one use case.

Negative:

- When a handler needs an external result to compute its write, it still holds
  a transaction across that call. Protean answers with guidance and, once
  built, a diagnostic. An operator who ignores both will hold locks across the
  network.
- Protean's implementation has to keep the "no repository access, no
  transaction" guarantee. Protean can no longer open a session eagerly at no
  cost. If it did, handler methods that only call out would start holding
  connections.
- When you split persistence from external calls, you write more handler
  methods. The value one method needs from the other travels on an event.

## Alternatives Considered

- **`@handle(Event, unit_of_work=False)`**, the original request. Rejected on
  granularity and on safety. The `unit_of_work=False` flag is Spring's
  `NOT_SUPPORTED` applied to a whole handler instead of a block. So the flag
  switches off OCC retry and the idempotency policy for everything else the
  handler does. Worse, delivery is at-least-once: when a handler commits three
  sub-units and fails on the fourth, the engine redelivers the message. The
  handler re-applies the first three, and a visible full rollback becomes a
  silent duplicate. Django's `non_atomic_requests` is the closest precedent. It
  is safe in Django because HTTP requests are not redelivered. Messages are.

- **A `prepare=` phase on `@handle`**, running before the transaction and not
  replayed on retry. Rejected because the boundary is too thin to explain and it
  fails a common case: a handler that must read aggregate state to decide whether
  to make the call cannot do the deciding in a phase that may not read.

- **A journaled side effect** in the style of Temporal's `SideEffect`, recording a
  result against `(message_id, key)` so retries and redeliveries read it back.
  Rejected as complexity in the wrong place. The journal would exist only to
  make the persist-and-call-out shape safe to retry and redeliver. The remote
  system's idempotency key already solves that problem, and only the remote
  system can guarantee it.

- **A suspend scope**, a context manager running a block with no transaction.
  Rejected as unnecessary. When you split the method, Protean gives the same
  result through the "no repository access, no transaction" guarantee. A split
  method is the shape we want developers to write anyway. ADR-0027 does not
  rule this out: its rejection of independent inner transactions rests on
  savepoint reasoning, and removing a transaction needs no savepoints.

- **Deterministic ordering for sibling handler methods.** Rejected. If Protean
  made the order stable, it would invite handlers to depend on that order. This
  ADR rules out that coupling. Sibling methods are independent. The fix for the
  sibling-skipping defect is that a failure in one method no longer skips the
  others.
