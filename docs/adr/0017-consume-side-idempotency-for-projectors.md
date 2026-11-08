# ADR-0017: Consume-Side Idempotency for Projectors

**Status:** Accepted

**Date:** July 2026

> Amended November 2026 (#1932), see
[Amendment](#amendment-november-2026-broker-subscribers) below.

## Context

Event delivery to projectors is **at-least-once**. Two independent paths replay
the *same* event (same `metadata.headers.id`):

- the outbox reclaims a row whose broker publish succeeded but whose
  `mark_published` did not commit before a crash, and republishes it;
- a broker redelivers a message whose projector UnitOfWork already committed but
  which was not yet acked.

Protean had no consume-side de-duplication, so a **non-idempotent** projector
(the classic `total_reviews += 1` accumulator) double-applies a redelivered
event and corrupts its read model. A naive "projection == fold(events)"
convergence check misses the failure, because that check folds the same
duplicated stream the projector saw. Only a check that computes its expected
value independently of the stream catches the failure (#1042).

Three facts shape the design:

1. **A stable key exists**: `metadata.headers.id` is deterministic
   (`<stream>-<aggregate-id>-<version>.<n>`) and identical on every redelivery.
2. **Each projector method already runs in its own UnitOfWork** (the `@handle`
   wrapper), so a dedup marker written inside that method's transaction commits
   or rolls back atomically *with* the read-model write. **This holds only when
   a transactional provider backs the projection.**
3. **Exactly-once cannot span two stores**: A projection can be cache-backed
   (Redis); a relational marker and a Redis read-model write are two systems
   with no shared transaction, the same two-store limit as ADR-0015. The
   existing command `IdempotencyStore` (Redis, caller-key, records success *after* the handler
   commits) is likewise non-atomic and does not fit.

## Decision

Provide **opt-in, atomic consume-side idempotency for projectors**.

1. **Opt in per projector:** `@domain.projector(idempotent=True)`.
2. **Per-provider marker**: A framework `ProcessedMessage` aggregate is
   synthesized per managed provider (mirroring the outbox), with a **unique
   index on `(message_id, handler)`**. `handler` is the fully-qualified handler
   method (`module.Class.method`) so distinct projectors/methods dedupe
   independently.
3. **Atomic check-and-mark**: In the `@handle` wrapper's UnitOfWork, an
   idempotent projector first checks the marker for `(message_id, handler)`; if
   present it **skips** (the redelivery is a no-op), otherwise it runs the method
   and writes the marker **in the same transaction** as the read-model write.
   The marker repository is resolved for the *projection's* provider so the two
   writes share one transaction.
4. **On a relational provider the unique index is the concurrency guarantee.**
   Two concurrent redeliveries both miss the check and both attempt to write the
   marker; the index rejects the second commit, so exactly one applies. The
   in-memory provider materializes neither the unique index nor real
   transactions, so there it degrades to the sequential ``is_processed`` skip
   only, which fixes ordinary redelivery but leaves concurrent redelivery
   unguarded. The in-memory provider is for development, and production
   idempotency should use a relational projection.
5. **Off by default, zero-cost when unused**: The marker table is created only
   when a projector opts in (`Domain.has_idempotent_consumers`).
6. **Scope: projectors**: Event handlers that write to arbitrary aggregates are
   out of scope for this decision (a projector has a single, known projection
   provider, which is what makes the marker atomic). Broker subscribers opt in
   too, under the
   [Amendment](#amendment-november-2026-broker-subscribers).

## Consequences

Positive:

- A redelivered event no longer corrupts an `idempotent=True` projector's read
  model on a transactional provider, exactly-once **at the projection
  boundary**.
- Concurrency-safe via the unique index **on a relational provider** (see
  Decision point 4 for the in-memory caveat).
- Opt-in and gated, so domains that don't use it carry no extra cost.

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
- **Throughput cost** on opt-in projectors: one extra indexed read + write per
  processed message.
- **Marker growth is bounded by retention, not automatic**: The marker table
  gains one row per ``(message_id, handler)``, and `is_processed` reads it on
  every delivery. `protean idempotency cleanup` prunes markers older than
  ``[consume_idempotency.cleanup].retention_hours`` (default 7 days) in bounded
  batches; operators run it periodically (e.g. cron). It is not auto-scheduled
  today; wiring it into an Engine maintenance tick (as ``DLQMaintenanceTask``
  does for the DLQ) is a possible future enhancement. A marker is only useful
  while its event can still be redelivered, so pruning past that window is safe.
  Because `handler` is `module.Class.method`, renaming a projector method
  orphans its old markers (the cleanup eventually removes them). The rename
  also opens a brief double-apply window for in-flight redeliveries across
  that deploy.
- This does not make Protean exactly-once across stores; it is exactly-once only
  *within one transactional provider*.

## Alternatives Considered

**Redis seen-store mirroring command idempotency.** Rejected: a Redis marker is
not atomic with the read-model write, so a crash between the projector commit
and the marker write re-opens the double-apply window. It would give false
exactly-once confidence.

**Documentation only, "projectors must be idempotent."** Retained as the
guidance for the non-transactional case, but insufficient on its own: some
projectors genuinely need dedup and cannot be expressed as pure upserts.

**Dedup at the subscription / ack layer.** Rejected: the broker ack and the
read-model write are in different systems, so the marker would again be
non-atomic, the same gap this decision closes by putting the marker *in the
projection's transaction*.

## Amendment (November 2026): broker subscribers

**Context:** A broker subscriber has the same at-least-once delivery as a
projector. A subscriber that issues a command or writes an aggregate applies a
redelivered message twice. Its only defence was a hand-written marker table.

**Amended decision:**

1. **Opt in per subscriber:** `@domain.subscriber(idempotent=True)`. The option
   is off by default, and a subscriber without it runs as before, with no unit
   of work added.
2. **The subscriber names the marker's provider:** `provider` (default
   `"default"`). A subscriber has no projection to read a provider from, so it
   states one. The marker goes to that provider in the same unit of work as the
   subscriber's writes. `domain.init()` raises a `ConfigurationError` when an
   idempotent subscriber names a provider that is not configured or not
   managed, because such a provider has no marker table.
3. **The key is the payload's id:** the marker is
   `(metadata.headers.id, subscriber fully-qualified class name)`. The
   broker-assigned delivery id is never the key, because a redelivery can carry
   a new one.
4. **A missing id is an error:** an idempotent subscriber that receives a
   payload with no non-blank string `metadata.headers.id`, or one longer than
   the marker's 255-character column, logs an error and raises
   `InsufficientDataError` without calling the subscriber. The Engine treats it
   as a failed message and calls `handle_error`; a synchronous `publish` raises
   it. Running without deduplication would ignore the opt-in.
5. **Same atomicity rules:** the check, the subscriber call and the marker
   write share one unit of work, and the marker is written only after the
   subscriber returns. The guarantees and limits of Decision point 4 and the
   Consequences apply unchanged, keyed on the subscriber's provider. They cover
   writes made through repositories on that provider. A command the subscriber
   issues with `domain.process` is stored in the event store at once, and an
   event store that writes outside the unit of work, such as Message DB, keeps
   it after a rollback, so a redelivery after a raise issues it again. Side
   effects outside the database repeat the same way.

**Consequences:** `Domain.has_idempotent_consumers` also counts subscribers, so
a domain whose only idempotent consumer is a subscriber gets the marker table
and the cleanup. Renaming or moving a subscriber class orphans its markers, as
renaming a projector method does.
