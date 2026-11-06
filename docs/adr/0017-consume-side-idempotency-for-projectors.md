# ADR-0017: Consume-Side Idempotency for Projectors

**Status:** Accepted

**Date:** July 2026

## Context

Event delivery to projectors is **at-least-once**. Two independent paths replay
the *same* event (same `metadata.headers.id`):

- the outbox publishes a row to the broker, crashes before `mark_published`
  commits, and then reclaims and republishes the row;
- a projector UnitOfWork commits a message, and the broker redelivers the
  message because it has not yet received the ack.

Protean had no consume-side de-duplication, so a **non-idempotent** projector
(the classic `total_reviews += 1` accumulator) double-applies a redelivered
event and corrupts its read model. A naive "projection == fold(events)"
convergence check misses the failure, because that check folds the same
duplicated stream the projector saw. Only a check that computes its expected
value independently of the stream catches the failure (#1042).

The design follows from three facts:

1. **A stable key exists**: `metadata.headers.id` is deterministic
   (`<stream>-<aggregate-id>-<version>.<n>`) and identical on every redelivery.
2. **Each projector method already runs in its own UnitOfWork** (the `@handle`
   wrapper), so a dedup marker written inside that method's transaction commits
   or rolls back atomically *with* the read-model write. **This holds only when
   a transactional provider backs the projection.**
3. **Exactly-once cannot span two stores**: A projection can be cache-backed
   (Redis); a relational marker and a Redis read-model write are two systems
   with no shared transaction, the same two-store limit as the decision on the
   event-store append in the commit sequence (ADR-0015). The existing command
   `IdempotencyStore` (Redis, caller-key, records success *after* the handler
   commits) is likewise non-atomic and does not fit.

## Decision

Provide **opt-in, atomic consume-side idempotency for projectors**.

1. **Opt in per projector:** `@domain.projector(idempotent=True)`.
2. **Keep one marker per provider**: Protean synthesizes a framework
   `ProcessedMessage` aggregate for each managed provider (mirroring the
   outbox), with a **unique index on `(message_id, handler)`**. `handler` is
   the fully-qualified handler method (`module.Class.method`) so distinct
   projectors/methods dedupe independently.
3. **Check and mark atomically**: In the `@handle` wrapper's UnitOfWork, an
   idempotent projector first checks the marker for `(message_id, handler)` and
   **skips** when the marker is present (the redelivery is a no-op). Otherwise
   the projector runs the method and writes the marker **in the same
   transaction** as the read-model write. Protean resolves the marker
   repository for the *projection's* provider so the two writes share one
   transaction.
4. **On a relational provider the unique index is the concurrency guarantee.**
   Two concurrent redeliveries both miss the check and both attempt to write
   the marker; the index rejects the second commit, so exactly one applies. The
   in-memory provider materializes neither the unique index nor real
   transactions, so it degrades to the sequential ``is_processed`` skip, which
   guards against ordinary redelivery and leaves concurrency unguarded. Use a
   relational projection for production idempotency, because in-memory is a
   development provider.
5. **Off by default, zero-cost when unused**: The marker table is created only
   when a projector opts in (`Domain.has_idempotent_consumers`).
6. **Apply the option to projectors only**: A projector has a single, known
   projection provider, and that one provider makes the marker atomic. An event
   handler can write to arbitrary aggregates, so event handlers are out of
   scope for this decision.

## Consequences

Positive:

- A redelivered event no longer corrupts an `idempotent=True` projector's read
  model on a transactional provider, exactly-once **at the projection
  boundary**.
- Concurrency-safe via the unique index **on a relational provider** (see
  Decision point 4 for the in-memory caveat).
- The option is opt-in and gated, so a domain without idempotent projectors
  gets no marker table and no extra cost.

Negative / boundaries (documented, not hidden):

- **Not universal**: When the projection is cache-backed, or writes span a
  provider different from the marker's, the marker is **not** atomic with the
  read-model write. In that case the option resolves to a no-op and the
  projector must be written as an **idempotent upsert**. The guide describes
  this case, and Protean logs it at debug level.
- **Concurrent-redelivery loser surfaces a conflict**: The losing writer's
  commit hits the unique index and raises, so its delivery fails and reports an
  error. The next redelivery finds the marker and skips, which gives eventual
  correctness within the at-least-once contract.
- **Opt-in projectors lose some throughput**: one extra indexed read + write
  per processed message.
- **Run a retention cleanup to bound marker growth**: The marker table gains
  one row per ``(message_id, handler)``. `is_processed` reads the marker table
  on every delivery. `protean idempotency cleanup` prunes markers older than
  ``[consume_idempotency.cleanup].retention_hours`` (default 7 days) in bounded
  batches; operators run it periodically (e.g. cron). It is not auto-scheduled
  today; wiring it into an Engine maintenance tick (as ``DLQMaintenanceTask``
  does for the DLQ) is a possible future enhancement. A marker is only useful
  while its event can still be redelivered, so pruning past that window is
  safe. Because `handler` is `module.Class.method`, renaming a projector method
  orphans its old markers (the cleanup eventually removes them). The rename
  also opens a brief double-apply window for in-flight redeliveries across that
  deploy.
- This does not make Protean exactly-once across stores; it is exactly-once only
  *within one transactional provider*.

## Alternatives Considered

**Keep a Redis seen-store, as command idempotency does.** Rejected: a Redis
marker is not atomic with the read-model write, so a crash between the
projector commit and the marker write re-opens the double-apply window. It
would give false exactly-once confidence.

**Only document that "projectors must be idempotent."** Retained as the
guidance for the non-transactional case, but insufficient on its own: some
projectors genuinely need dedup and cannot be expressed as pure upserts.

**De-duplicate at the subscription / ack layer.** Rejected: the broker ack and
the read-model write are in different systems, so the marker would again be
non-atomic. Protean closes that gap by putting the marker *in the projection's
transaction*.
