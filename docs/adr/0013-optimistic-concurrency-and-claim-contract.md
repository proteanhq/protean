# ADR-0013: Atomic Find-and-Claim Contract for Concurrent Consumers

**Status:** Accepted

**Date:** June 2026

## Context

The outbox is the framework default for reliable message delivery, so it sits on
the hot path of every Protean deployment that publishes events. The
`OutboxProcessor` historically pulled work in two steps per poll:

1. `find_unprocessed(limit=N)` — a `SELECT` returning up to `N` eligible rows.
2. For each row, `claim_for_processing(row, worker_id)` — an
   `UPDATE … WHERE id = :id AND status IN (pending, failed)` that marks the row
   `processing` and locks it.

This has two problems on a contended table:

- **A TOCTOU window.** Between the `SELECT` and the per-row `UPDATE`, another
  worker can claim the same row. The guarded `UPDATE` *detects* the loss (the
  `WHERE` no longer matches, rowcount is `0`) but does not *prevent* it — the
  loser has already paid for a wasted round trip and produces "already claimed"
  log noise.
- **`1 + N` round trips per batch.** One `SELECT` plus `N` `UPDATE`s. At high
  throughput the per-row latency dominates the poll cost.

The same shape recurs for any high-throughput consumer that pulls a bounded
batch of rows and marks them in-flight (process-manager correlation lookups,
projection rebuild cursors, retention sweeps). The need is broader than the
outbox, so the contract belongs at the DAO layer, not buried in the outbox
repository.

## Decision

We introduce a DAO-level primitive, `BaseDAO._claim(criteria,
claim_fields, limit, order_by=None)`, that selects up to `limit` rows matching
`criteria`, applies `claim_fields` as an update, and returns the claimed rows in
post-claim state. Implementations must guarantee that no two callers observe the
same row as claimed (no double-claim) and that the returned rows reflect the
applied `claim_fields`. Non-blocking is not part of the contract: only the
`FOR UPDATE SKIP LOCKED` fast path steps over locked rows without waiting; the
portable default may briefly block on a contended row before its guard rejects
the claim.

**Portable default (`BaseDAO`).** Reads candidates via the entity query API,
then issues a guarded `UPDATE … WHERE id = :id AND <criteria>` per row. The
re-asserted criteria make a row another worker already claimed fail to match.
This is `1 + N` round trips — identical in cost to the old flow — and is the
correctness floor, not the performance target. It prevents double-claim on every
backend, but the *failure mode* of a lost race differs: relational backends
(PostgreSQL, MySQL, SQL Server) re-evaluate the guard under the row lock and
return zero rows (graceful skip); SQLite serializes writers (a contended write
may raise `SQLITE_BUSY`); Elasticsearch relies on document versioning, so the
second writer hits a version conflict and the call raises rather than skipping.
Elasticsearch is therefore not recommended as a concurrently-consumed claim
store.

**SQLAlchemy fast path (PostgreSQL only).** A single statement:

```sql
UPDATE <table> SET <claim_fields>
WHERE id IN (
    SELECT id FROM <table> WHERE <criteria>
    ORDER BY <order> LIMIT <n> FOR UPDATE SKIP LOCKED
)
RETURNING *
```

The inner `FOR UPDATE SKIP LOCKED` locks eligible rows and steps over rows other
workers hold; the enclosing `UPDATE` claims exactly those rows; `RETURNING`
hands them back — one round trip, no TOCTOU window. `RETURNING` does not
preserve the inner `ORDER BY`, so the returned batch is re-sorted in Python to
honour `order_by`.

**Memory adapter.** Holds the provider's `threading.Lock` across the whole
read-and-claim section and delegates to the portable default. The lock
serializes concurrent claimers in-process, which is the strongest guarantee the
single-process store can offer.

**MySQL/MariaDB, SQL Server, SQLite, Elasticsearch, and other dialects** use the
portable default. MySQL and MariaDB have `SKIP LOCKED` but no
`UPDATE … RETURNING`, so the single-statement form does not compile there; SQL
Server uses `OUTPUT` with different table-hint semantics; SQLite serializes
writers; Elasticsearch is non-relational. PostgreSQL is the only dialect that
offers `FOR UPDATE SKIP LOCKED` and `UPDATE … RETURNING` together, so it is the
sole fast-path dialect. A dedicated MySQL or MSSQL fast path can be added later
(two-statement lock-then-update, or `OUTPUT`) if profiling justifies it.

**Transaction boundary.** `_claim` commits the claim through the
DAO's standalone-commit path, so the lock and state change are durable the
moment it returns. It must therefore be called **outside** an active Unit of
Work — inside a UoW the write would not commit until the UoW does, so other
workers would not see the claim and the lock-then-return guarantee would not
hold. `OutboxProcessor.get_next_batch_of_messages` calls it with no surrounding
UoW, which is correct.

`OutboxRepository.claim_batch(worker_id, limit, target_broker=None)` is the new
public entry point, built on `_claim`, and `OutboxProcessor` uses it.
The claim now happens once when the batch is fetched, not per message during
processing. `OutboxRepository` is framework-internal plumbing (not part of the
public `protean.*` surface user code builds on), so no deprecation cycle
applies: `claim_for_processing` — the racy per-message claim that
`claim_batch` supersedes — is removed outright, while `find_unprocessed` is
kept as a read-only inspection query alongside its siblings (`find_failed`,
`find_abandoned`, `find_published`, `find_processing`).

This complements, rather than replaces, the optimistic-concurrency work from
epic 5.1 (`BaseDAO._validate_and_update_version`): version checking guards
*aggregate updates* against lost writes, while `_claim` guards
*queue-style claims* against double processing.

Both rely on the same principle: a guarded `UPDATE … WHERE <expected state>` so
the database, not the application, decides the winner. For aggregate updates the
adapter enforces this with SQLAlchemy's native **`version_id_col`**: Protean owns
the version value (`version_id_generator=False`, advanced by
`_validate_and_update_version`), and the ORM flush emits `UPDATE … SET … ,
_version = <new> WHERE id = :id AND _version = <loaded>`, raising `StaleDataError`
— translated to `ExpectedVersionError` at commit — when a concurrent write already
advanced the version. `version_id_col` is used here (rather than issuing an eager
`UPDATE … WHERE _version = :expected` from the adapter) because the SQLAlchemy
provider runs an **AUTOCOMMIT engine**: the UnitOfWork achieves atomicity by
deferring every write to a single flush at commit, so an eager statement would
autocommit mid-UoW and break transaction isolation and rollback. Because the
version predicate rides the deferred flush, the guard is atomic without a serial
isolation level while the write stays invisible until commit. A non-atomic
read-compare-write (read the version in Python, compare, then write
unconditionally) would *not* hold: two transactions can both read the same
version and both write, silently losing one update — the failure the guarded
`UPDATE` prevents.

**The aggregate root is the concurrency boundary — including child changes.**
The version guard above protects the root's own fields, but an aggregate can be
modified purely through a child entity (a `HasMany`/`HasOne` member): a change to
a line item's quantity, with no root-field change and no event. Such a change
persists the child through the un-versioned path (`_update(expected_version=None)`
— a child entity is not an aggregate, so `_validate_and_update_version` does not
run for it), and `Repository._do_add` re-saves the root only when the root itself
is new or changed. A child-only change would therefore leave the root's version
untouched, and two concurrent child-only updates would both succeed — the child
counterpart of the lost update above. We treat the aggregate root as the unit of
concurrency control: `Repository._do_add` re-saves the root not only when the
root's own fields changed but also when any persisted child was directly edited
(`_has_changed_child`, which mirrors the direct-update detection already in
`_sync_children`), so the guarded root save runs and advances `_version`. This
covers a child's scalar, value-object, and reference fields uniformly, because
the check reads the child's own `state_.is_changed` rather than the field kind.
Under a transactional provider the child writes and the root version bump commit
together in the Unit of Work.

Adding or removing a `HasMany` child through the `add_`/`remove_` collection
methods is deliberately out of scope: those methods do not mark the root changed,
`mark_changed` no-ops while a freshly added child is new (so it does not trip
`_has_changed_child`), and concurrent adds of distinct children do not race the
way concurrent edits of the same existing data do. Assigning or replacing a
`HasOne` child (`aggregate.child = ...`) is different — it goes through the root's
own `__setattr__`, marks the root changed, and is version-guarded like any
root-field change.

Because an aggregate that has child rows forces its root `UPDATE` out at
`repo.add` time (a flush to materialize the parent row before the child inserts
that reference it, since Protean emits no SQLAlchemy foreign-key metadata to let
the ORM order them) rather than at commit, a child-only version conflict can
surface at that forced flush instead of at commit. The SQLAlchemy `_flush`
translates the resulting `StaleDataError` to `ExpectedVersionError` there, the
same mapping the commit path applies.

## Consequences

- The outbox poll path drops from `1 + N` round trips to one (fast path) or
  stays at `1 + N` (portable default), with the TOCTOU window closed in both.
- "Already claimed" contention log noise disappears on the fast path — workers
  never select rows they cannot claim.
- Because the claim now happens once at batch fetch (not per message), a worker
  that dies after claiming but before publishing leaves the **whole claimed
  batch** in `processing` until `locked_until` expires. The eligibility criteria
  include `PROCESSING` rows whose lock has expired, so those rows are then
  reclaimed automatically (an actively-locked `PROCESSING` row is still
  excluded, so in-flight messages are never stolen). This is a wider stall
  window than the previous per-message claim (which stranded only the in-flight
  message), but it is still at-least-once and
  self-healing; size `locked_until` against `messages_per_tick` and expected
  processing time.
- New adapters get correct behaviour for free via the portable default;
  implementing the fast path is an opt-in optimization, not a requirement.
- The fast path depends on the SQL backend supporting `SKIP LOCKED` and
  `RETURNING`. The dialect allow-list (`_SKIP_LOCKED_DIALECTS`) keeps the
  decision explicit; an unlisted dialect silently and correctly uses the
  portable default.

## Alternatives Considered

- **Ship only the portable default.** Rejected — it is the same `1 + N` cost as
  today; the round-trip win is the whole point.
- **`SELECT … FOR UPDATE SKIP LOCKED` followed by a separate `UPDATE`.** Rejected
  — observed double-claims in testing because the row locks taken by the `SELECT`
  were not reliably held across the Python round trip to the separate `UPDATE`,
  and it is still two statements. The single `UPDATE … RETURNING` with the
  locking sub-select is atomic and avoids the window entirely.
- **Hand-rolled raw SQL per dialect (CTEs, `OUTPUT` for MSSQL, two-statement for
  MySQL).** Rejected for now — PostgreSQL renders the whole claim from one
  SQLAlchemy Core construct (`UPDATE … FOR UPDATE SKIP LOCKED … RETURNING`),
  which is far less to maintain and get wrong, and it is the dialect most likely
  to run a high-throughput outbox. MySQL/MariaDB (no `UPDATE … RETURNING`) and
  MSSQL (`OUTPUT` + different table hints) would each need bespoke SQL, so they
  use the portable default for now; dedicated fast paths can be added later if
  profiling justifies them.
- **Put dialect dispatch in `OutboxRepository`.** Rejected — the contract is
  broader than the outbox and belongs at the DAO layer where other consumers can
  reuse it.
