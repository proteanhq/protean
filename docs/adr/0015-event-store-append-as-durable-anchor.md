# ADR-0015: Event-Store Append as the Durable Anchor in the Commit Sequence

**Status:** Proposed

> Amended November 2026: a SQL event store that shares the `default` database
provider now appends inside the Unit of Work's transaction (see the amendment
to decision 1 and > [ADR-0048](0048-sql-event-store.md)).

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

The order matters. The outbox rows are committed with the relational
transaction in step 1, before the events reach the event store in step 2. If
the process dies or the event-store write fails between the two writes, the
relational side is durable. The event store is then missing the events. The
consequences differ by aggregate style:

- For an event-sourced aggregate the event store is the source of truth.
  `from_events()` reconstructs a state that is missing the lost event. The
  committed write and the replayable history then diverge silently. The
  aggregate's optimistic-concurrency version has already advanced and the
  outbox row exists, but the event that justifies them is gone.
- For a CQRS aggregate the relational state is intact, but the event store
  (used for audit and projection rebuilds) is incomplete. The outbox still
  publishes events the store does not contain.

In both cases consumers can receive, through the outbox, events that the event
store has no record of. The divergence is invisible to in-memory tests (a single
store) and to convergence checks; it only appears under a crash in the window
against a real two-store setup.

Every option has to work with one constraint: the relational database and the
event store are independent systems. Neither Message DB nor EventStoreDB
participates in a two-phase commit with the aggregate database. Protean does
not want to take on a distributed-transaction coordinator. So the problem
cannot be solved by making the two writes truly atomic. Protean must instead
choose which store is the durable anchor and make the failure mode recoverable
so that it does not corrupt data.

Both supported event stores provide the optimistic-concurrency primitive needed
to make a repeated append safe. Message DB appends with an `expected_version`;
a re-append at an already-advanced position is rejected as a conflict.
EventStoreDB goes further and guards appends with `expected_revision`. Its
appends are also idempotent by `EventId`: re-appending the same event id at a
compatible position is a no-op. The decision on the atomic find-and-claim
contract for concurrent consumers (ADR-0013) records this same concurrency
contract.

## Decision

We will make the event-store append the **durable anchor** of the commit
sequence: the first write that becomes durable, which the relational commit and
outbox follow.

1. **Reorder**: `UnitOfWork._do_commit` appends events to the event store first,
   and only then commits the relational session that carries aggregate state
   and the outbox rows. The first durable write then goes to the event store,
   the source of truth for event-sourced aggregates.

   *Amended (November 2026, ADR-0048): when a SQL event store shares the
   `default` database provider, it appends inside the Unit of Work's
   transaction. Events, aggregate rows and outbox rows then commit or roll back
   together, as one relational commit. The append is no longer a separate
   durable write, so reconciliation has no window to repair. This decision
   applies unchanged to every event store that commits each append on its own
   connection, including a SQL event store configured with `database_uri`.*

2. **Idempotent on retry**: Because a commit can be retried after a partial
   failure (the append succeeds, the relational commit fails), the append must
   be safe to repeat. We rely on the event store's optimistic-concurrency
   contract, keyed on a stable event id (Protean's `_metadata.headers.id`): a
   repeated append of the same events at the same expected position is
   recognized as already-applied and treated as success, while a genuine
   concurrent write surfaces as a real conflict and aborts the commit.
   EventStoreDB satisfies the contract natively through `EventId` idempotency.
   Message DB satisfies it through `expected_version` plus an already-applied
   check.

3. **Event-store-agnostic**: The decision is expressed as a principle about
   ordering and idempotency, not about a particular backend. It holds unchanged
   for the in-memory store, Message DB, and a future EventStoreDB adapter.

4. **Reconcile and repair the outbox**: Once `UnitOfWork._do_commit` appends
   first, a failure is recoverable (events durable in the store, but the outbox
   rows or relational state not yet committed) instead of unrecoverable (the
   event store missing a committed event). We will provide reconciliation that
   detects this divergence and repairs it by deriving the missing outbox rows
   from the event store, exposed two ways: an explicit **repair command**
   operators run on demand, and an **automatic sweep on server startup** so
   that a crash before the relational commit self-heals when the process
   restarts (for event-sourced aggregates only, see the amendment below). Both
   ship alongside the reorder, not as a later phase. We accept that this is an
   interim detection-and-repair surface rather than the final guarantee (see
   the outbox-style write-ahead alternative); the intent is to maximize
   detection and recovery while the larger mechanism is deferred.

   *Amended (November 2026, #1908): reconciliation rebuilds outbox rows only
   for events of event-sourced aggregates. For a state-based aggregate the
   relational row is the state, and on a transactional provider that row
   commits or rolls back with its outbox rows. An event of such an aggregate
   with no outbox row therefore has no saved change behind it. A crash before
   the relational commit therefore self-heals on restart only for event-sourced
   aggregates. On a provider without transactions, such as Elasticsearch, a
   state-based aggregate's saved change whose outbox row was lost stays
   unpublished. The commit order in decision 1, event-store append first, is
   unchanged.*

## Consequences

Positive:

- The event store, the source of truth for event-sourced replay, can no longer be
  left missing a committed event. The corrupting failure mode is eliminated.
- The remaining failure window (events stored, outbox or relational state not
  yet committed) is recoverable for event-sourced aggregates, because
  reconciliation can re-derive their outbox rows from the event store. The
  aggregate itself already reconstructs correctly from the store.
  Reconciliation does not re-derive the events of state-based aggregates (see
  the amendment to decision 4).
- The contract is the same across every event store. Adopting EventStoreDB at
  scale needs no change to the commit ordering. EventStoreDB's native `EventId`
  idempotency also makes the retry path simpler than Message DB's.
- The decision composes with the existing optimistic-concurrency and claim
  contract (ADR-0013) rather than introducing a new mechanism.

Negative:

- The relational transaction now stays open across the event-store append round
  trip (the writes are buffered, the event store is appended, then the
  relational session commits). With a nearby Message DB the append is cheap.
  With a remote or clustered EventStoreDB, the round trip lengthens the
  lock-hold window and can increase contention under load. The implementation
  must keep the relational transaction minimal around the append. We must also
  benchmark the longer transaction against the two-store setup.
- Message DB's retry path needs an explicit already-applied check to distinguish
  a self-retry from a real concurrent-writer conflict. EventStoreDB does not
  need that check, but the framework code must implement both retry paths.
- Reconciliation and repair add two new parts to build, test, and operate: a
  repair command and a startup sweep. The startup sweep adds bounded work to
  server boot (a scan for unreconciled events), and it must stay bounded in the
  common case where there is nothing to repair. It reads at most the configured
  window of recent messages and looks up their outbox rows in batches. Protean
  takes on the repair command and the startup sweep because it has no true
  cross-store atomicity.
- The reordered commit sequence is not a two-phase commit. A narrow window
  remains in which events are durable but their outbox rows are not yet
  committed. Reconciliation makes that window recoverable for event-sourced
  aggregates, but it does not remove the window.

## Alternatives Considered

**Outbox-style write-ahead for the event store.** Write the pending event-store
appends into the relational transaction itself (atomic with aggregate state and
the outbox), then have a background processor append them to the event store
idempotently, exactly as the outbox publishes to brokers. This write-ahead
approach makes the relational commit the single atomic boundary. It is the end
state with the strongest guarantee. We deferred it because it is a
substantially larger build (a new pending-writes store, a processor, ordering
and version guarantees) and makes the event store eventually consistent.
Read-your-own-writes then breaks for event-sourced aggregates unless the read
path also consults the pending writes. We record it as the likely future
direction beyond this decision.

**Same-transaction append when the stores coincide.** When the event store is
backed by the same relational database as the aggregate, the append can join the
same transaction and be truly atomic. This is a real win for that configuration
but does not help the deployments that matter here, where the event store
(Message DB, EventStoreDB) is a separate system.

**Two-phase commit across the stores.** Rejected. Neither Message DB nor
EventStoreDB offers practical XA participation with the aggregate database. A
distributed-transaction coordinator adds complexity and operational fragility
that the framework does not want to own.

**EventStoreDB subscriptions as the delivery mechanism.** At scale,
EventStoreDB's persistent subscriptions and `$all` stream can drive broker
delivery directly, which would let the event store replace the relational
outbox for the publish path. With that change the event store is both the
source of truth and the reliable-delivery mechanism, so almost none of the
two-store problem remains. No separate outbox transaction has to stay
consistent with the event store. This is the natural evolution once an
EventStoreDB adapter exists. This ADR's commit order is a correct interim step
toward that design. Protean will not have to undo it to adopt EventStoreDB
subscriptions for delivery.

**Document the window only.** The issue that raised this problem asked, at
minimum, to document the window and provide a repair path. Documentation alone
leaves the corrupting failure mode in place for event-sourced aggregates. That
failure mode is the core defect, so documentation is insufficient on its own.
We keep the repair path as part of this decision. The reorder in decision 1 is
the change that stops the event store from missing committed events.
