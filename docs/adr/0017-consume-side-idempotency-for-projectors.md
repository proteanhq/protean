# ADR-0017: Consume-Side Idempotency for Projectors

**Status:** Accepted

**Date:** July 2026

## Context

Event delivery to projectors is **at-least-once**. Two independent paths replay
the *same* event (same `metadata.headers.id`):

- the outbox reclaims a row whose broker publish succeeded but whose
  `mark_published` did not commit before a crash, and republishes it;
- a broker redelivers a message whose projector UnitOfWork already committed but
  which was not yet acked.

Protean had no consume-side de-duplication, so a **non-idempotent** projector —
the classic `total_reviews += 1` accumulator — double-applies a redelivered
event and corrupts its read model. The failure hides from a naive
"projection == fold(events)" convergence check, because that check folds the
same duplicated stream the projector saw; only a check whose expected value is
computed independently of the stream catches it (#1042).

Three facts shape the design:

1. **A stable key exists.** `metadata.headers.id` is deterministic
   (`<stream>-<aggregate-id>-<version>.<n>`) and identical on every redelivery.
2. **Each projector method already runs in its own UnitOfWork** (the `@handle`
   wrapper), so a dedup marker written inside that method's transaction commits
   or rolls back atomically *with* the read-model write — **but only if the
   projection is backed by a transactional provider.**
3. **Exactly-once cannot span two stores.** A projection can be cache-backed
   (Redis); a relational marker and a Redis read-model write are two systems
   with no shared transaction — the same two-store limit as ADR-0015. The
   existing command `IdempotencyStore` (Redis, caller-key, records success
   *after* the handler commits) is likewise non-atomic and does not fit.

## Decision

Provide **opt-in, atomic consume-side idempotency for projectors**.

1. **Opt in per projector:** `@domain.projector(idempotent=True)`.
2. **Per-provider marker.** A framework `ProcessedMessage` aggregate is
   synthesized per managed provider (mirroring the outbox), with a **unique
   index on `(message_id, handler)`**. `handler` is the fully-qualified handler
   method (`module.Class.method`) so distinct projectors/methods dedupe
   independently.
3. **Atomic check-and-mark.** In the `@handle` wrapper's UnitOfWork, an
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
   only (fixes ordinary redelivery, not concurrency); in-memory is a development
   provider and production idempotency should use a relational projection.
5. **Off by default, zero-cost when unused.** The marker table is created only
   when a projector opts in (`Domain.has_idempotent_consumers`).
6. **Scope: projectors.** Event handlers that write to arbitrary aggregates are
   out of scope for this decision (a projector has a single, known projection
   provider, which is what makes the marker atomic).

## Consequences

Positive:

- A redelivered event no longer corrupts an `idempotent=True` projector's read
  model on a transactional provider — exactly-once **at the projection boundary**.
- Concurrency-safe via the unique index **on a relational provider** (see
  Decision point 4 for the in-memory caveat).
- Opt-in and gated, so domains that don't use it pay nothing.

Negative / boundaries (documented, not hidden):

- **Not universal.** When the projection is cache-backed, or writes span a
  provider different from the marker's, the marker is **not** atomic with the
  read-model write. In that case the option resolves to a no-op and the
  projector must be written as an **idempotent upsert**. This is surfaced in the
  guide and logged at debug.
- **Concurrent-redelivery loser surfaces a conflict.** The losing writer's
  commit hits the unique index and raises; its delivery fails and the subsequent
  redelivery finds the marker and skips — eventual correctness within the
  at-least-once contract, but one delivery reports an error.
- **Throughput cost** on opt-in projectors: one extra indexed read + write per
  processed message.
- **Unbounded marker growth.** The marker table gains one row per
  ``(message_id, handler)`` forever; unlike the outbox it has no cleanup/TTL
  today, and `is_processed` reads it on every delivery. Operators should prune
  markers older than their redelivery/recovery window (retention is tracked as a
  follow-up). Note also that `handler` is `module.Class.method`: renaming a
  projector method orphans its old markers and opens a brief double-apply window
  for in-flight redeliveries across that deploy.
- This does not make Protean exactly-once across stores; it is exactly-once only
  *within one transactional provider*.

## Alternatives Considered

**Redis seen-store mirroring command idempotency.** Rejected: a Redis marker is
not atomic with the read-model write, so a crash between the projector commit
and the marker write re-opens the double-apply window. It would give false
exactly-once confidence.

**Documentation only — "projectors must be idempotent."** Retained as the
guidance for the non-transactional case, but insufficient on its own: some
projectors genuinely need dedup and cannot be expressed as pure upserts.

**Dedup at the subscription / ack layer.** Rejected: the broker ack and the
read-model write are in different systems, so the marker would again be
non-atomic — the same gap this decision closes by putting the marker *in the
projection's transaction*.
