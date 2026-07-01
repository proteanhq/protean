# ADR-0015: Event-Store Append as the Durable Anchor in the Commit Sequence

**Status:** Proposed

**Date:** June 2026

## Context

`UnitOfWork._do_commit` finalizes a transaction by making two separate durable
writes to two different datastores, with no atomicity spanning them:

1. `session.commit()` commits the relational transaction: aggregate state (for
   non-event-sourced aggregates) and every outbox row for the events raised in
   the unit of work.
2. A subsequent loop appends those same events to the event store
   (`current_domain.event_store.store.append(event)`), which for a real
   deployment is a distinct datastore (Message DB today, EventStoreDB at scale).

The order matters. The outbox rows are committed with the relational transaction
in step 1, before the events reach the event store in step 2. If the process
dies, or the event-store write fails, in the window between the two, the
relational side is durable but the event store is missing the events. The
consequences differ by aggregate style:

- For an event-sourced aggregate the event store is the source of truth.
  `from_events()` reconstructs a state that is missing the lost event, so the
  committed write and the replayable history diverge silently. The aggregate's
  optimistic-concurrency version has already advanced and the outbox row exists,
  but the event that justifies them is gone.
- For a CQRS aggregate the relational state is intact, but the event store (used
  for audit and projection rebuilds) is incomplete, and the outbox will still
  publish events the store does not contain.

In both cases consumers can receive, through the outbox, events that the event
store has no record of. The divergence is invisible to in-memory tests (a single
store) and to convergence checks; it only appears under a crash in the window
against a real two-store setup.

The constraint that shapes every option is that the relational database and the
event store are independent systems. Neither Message DB nor EventStoreDB
participates in a two-phase commit with the aggregate database, and Protean does
not want to take on a distributed-transaction coordinator. So the problem cannot
be solved by making the two writes truly atomic. It must be solved by choosing
which store is the durable anchor and making the failure mode recoverable rather
than corrupting.

Both supported event stores provide the optimistic-concurrency primitive needed
to make a repeated append safe. Message DB appends with an `expected_version`; a
re-append at an already-advanced position is rejected as a conflict.
EventStoreDB goes further: appends are idempotent by `EventId` (re-appending the
same event id at a compatible position is a no-op) and guarded by
`expected_revision`. This is the same concurrency contract recorded in ADR-0013.

## Decision

We will make the event-store append the **durable anchor** of the commit
sequence, and make the relational commit and outbox follow it.

1. **Reorder.** `UnitOfWork._do_commit` appends events to the event store first,
   and only then commits the relational session that carries aggregate state and
   the outbox rows. The event store, which is the source of truth for
   event-sourced aggregates, becomes the first durable write.

2. **Idempotent on retry.** Because a commit can be retried after a partial
   failure (the append succeeds, the relational commit fails), the append must be
   safe to repeat. We rely on the event store's optimistic-concurrency contract,
   keyed on a stable event id (Protean's `_metadata.headers.id`): a repeated
   append of the same events at the same expected position is recognized as
   already-applied and treated as success, while a genuine concurrent write
   surfaces as a real conflict and aborts the commit. EventStoreDB satisfies this
   natively through `EventId` idempotency; Message DB satisfies it through
   `expected_version` plus an already-applied check.

3. **Event-store-agnostic.** The decision is expressed as a principle about
   ordering and idempotency, not about a particular backend. It holds unchanged
   for the in-memory store, Message DB, and a future EventStoreDB adapter.

4. **Reconciliation and repair.** Reordering moves the unrecoverable failure (the
   event store missing a committed event) to a recoverable one (events durable in
   the store, but the outbox rows or relational state not yet committed). We will
   provide reconciliation that detects this divergence and repairs it by deriving
   the missing outbox rows from the event store, exposed two ways: an explicit
   **repair command** operators run on demand, and an **automatic sweep on server
   startup** so that a crash before the relational commit self-heals when the
   process restarts. Both ship alongside the reorder, not as a later phase. We
   accept that this is an interim detection-and-repair surface rather than the
   final guarantee (see the outbox-style write-ahead alternative); the intent is
   to maximize detection and recovery while the larger mechanism is deferred.

## Consequences

Positive:

- The event store, the source of truth for event-sourced replay, can no longer be
  left missing a committed event. The corrupting failure mode is eliminated.
- The remaining failure window (events stored, outbox or relational state not yet
  committed) is recoverable: the outbox can be re-derived from the event store,
  and an event-sourced aggregate already reconstructs correctly from the store.
- The contract is the same across every event store. Adopting EventStoreDB at
  scale needs no change to the commit ordering, and EventStoreDB's native
  `EventId` idempotency makes the retry path simpler than Message DB's.
- The decision composes with the existing optimistic-concurrency and claim
  contract (ADR-0013) rather than introducing a new mechanism.

Negative:

- The relational transaction now stays open across the event-store append round
  trip (the writes are buffered, the event store is appended, then the relational
  session commits). With a local-ish Message DB the append is cheap, but with a
  remote or clustered EventStoreDB the round trip lengthens the lock-hold window
  and can increase contention under load. The implementation must keep the
  relational transaction minimal around the append, and we must benchmark this
  against the two-store setup.
- Message DB's retry path needs an explicit already-applied check to distinguish
  a self-retry from a real concurrent-writer conflict. EventStoreDB does not, but
  the framework code must handle both.
- A reconciliation and repair capability is new surface to build, test, and
  operate: a repair command and a startup sweep. The startup sweep adds bounded
  work to server boot (a scan for unreconciled events) and must be cheap in the
  common case where there is nothing to repair. It is the price of not having
  true cross-store atomicity.
- This is not two-phase commit. A narrow window remains in which events are
  durable but their outbox rows are not yet committed. The design makes that
  window recoverable rather than lossy; it does not remove it.

## Alternatives Considered

**Outbox-style write-ahead for the event store.** Write the pending event-store
appends into the relational transaction itself (atomic with aggregate state and
the outbox), then have a background processor append them to the event store
idempotently, exactly as the outbox publishes to brokers. This makes the
relational commit the single atomic boundary and is the most robust end state. It
was deferred because it is a substantially larger build (a new pending-writes
store, a processor, ordering and version guarantees) and because it makes the
event store eventually consistent, which breaks read-your-own-writes for
event-sourced aggregates unless the read path also consults the pending writes.
We record it as the likely future direction beyond this decision.

**Same-transaction append when the stores coincide.** When the event store is
backed by the same relational database as the aggregate, the append can join the
same transaction and be truly atomic. This is a real win for that configuration
but does not help the deployments that matter here, where the event store
(Message DB, EventStoreDB) is a separate system.

**Two-phase commit across the stores.** Rejected. Neither Message DB nor
EventStoreDB offers practical XA participation with the aggregate database, and a
distributed-transaction coordinator is complexity and operational fragility the
framework does not want to own.

**EventStoreDB subscriptions as the delivery mechanism.** At scale,
EventStoreDB's persistent subscriptions and `$all` stream can drive broker
delivery directly, which would let the event store replace the relational outbox
for the publish path. That collapses the two-store problem almost entirely: the
event store becomes both the source of truth and the reliable-delivery
mechanism, and there is no separate outbox transaction left to keep consistent.
This is the natural evolution once an EventStoreDB adapter exists. The decision
here is the correct interim that evolves toward it rather than a design that must
be unwound for it.

**Document the window only.** The issue's stated minimum was to document the
window and provide a repair path. Documentation alone leaves the corrupting
failure mode in place for event-sourced aggregates, which is the core defect, so
it is insufficient on its own. The repair path is retained as part of this
decision; the reorder is what closes the corruption.
