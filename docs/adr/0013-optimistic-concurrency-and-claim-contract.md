# ADR-0013: Atomic Find-and-Claim Contract for Concurrent Consumers

**Status:** Accepted

> Amended October 2026, see
[Amendment](#amendment-october-2026-hold-back) below.

**Date:** June 2026

## Context

The outbox is the framework default for reliable message delivery, so every
Protean deployment that publishes events runs it on the hot path. The
`OutboxProcessor` historically pulled work in two steps per poll:

1. `find_unprocessed(limit=N)`: A `SELECT` returning up to `N` eligible rows.
2. For each row, `claim_for_processing(row, worker_id)`, an `UPDATE … WHERE id = :id AND status IN (pending, failed)` that marks the row `processing` and locks it.

This has two problems on a contended table:

- **A TOCTOU window**: Between the `SELECT` and the per-row `UPDATE`, another
  worker can claim the same row. The guarded `UPDATE` *detects* the loss (the
  `WHERE` no longer matches, rowcount is `0`) but does not *prevent* it. The
  losing worker has already spent a round trip for nothing. It also writes an
  "already claimed" message to the log.
- **`1 + N` round trips per batch**: One `SELECT` plus `N` `UPDATE`s. At high
  throughput the per-row latency dominates the poll cost.

Other high-throughput consumers have the same two problems when they read a
bounded batch of rows and mark them in-flight (process-manager correlation
lookups, projection rebuild cursors, retention sweeps). Other consumers need
the same claim, so the contract belongs in the DAO layer and not in the
outbox repository.

## Decision

We introduce a DAO-level primitive, `BaseDAO._claim(criteria,
claim_fields, limit, order_by=None)`, that selects up to `limit` rows matching
`criteria`, applies `claim_fields` as an update, and returns the claimed rows in
post-claim state. Implementations must guarantee that no two callers observe the
same row as claimed (no double-claim) and that the returned rows reflect the
applied `claim_fields`. The contract does not promise a non-blocking claim:
only the `FOR UPDATE SKIP LOCKED` fast path skips locked rows without waiting.
The portable default may briefly block on a contended row before its guard
rejects the claim.

**Portable default (`BaseDAO`).** Reads candidates via the entity query API,
then issues a guarded `UPDATE … WHERE id =:id AND <criteria>` per row. The
re-asserted criteria make a row another worker already claimed fail to match.
The portable default costs `1 + N` round trips (identical in cost to the old
flow). It is the correctness floor, not the performance target. It prevents
double-claim on every backend, but the *failure mode* of a lost race differs:
relational backends (PostgreSQL, MySQL, SQL Server) re-evaluate the guard under
the row lock and return zero rows (graceful skip); SQLite serializes writers (a
contended write may raise `SQLITE_BUSY`); Elasticsearch relies on document
versioning, so the second writer hits a version conflict and the call raises
rather than skipping. Elasticsearch is therefore not recommended as a
concurrently-consumed claim store.

**SQLAlchemy fast path (PostgreSQL only).** A single statement:

```sql
UPDATE <table> SET <claim_fields>
WHERE id IN (
    SELECT id FROM <table> WHERE <criteria>
    ORDER BY <order> LIMIT <n> FOR UPDATE SKIP LOCKED
)
RETURNING *
```

The inner `FOR UPDATE SKIP LOCKED` locks eligible rows and skips rows that
other workers hold. The enclosing `UPDATE` claims exactly the rows that the
inner query locked. `RETURNING` sends them back in the same statement, so the
claim takes one round trip and leaves no TOCTOU window. `RETURNING` does not
preserve the inner `ORDER BY`, so the returned batch is re-sorted in Python to
honour `order_by`.

**Memory adapter.** Holds the provider's reentrant lock (`threading.RLock`)
across the whole read-and-claim section and delegates to the portable default.
The lock serializes concurrent claimers in-process, which is the strongest
guarantee the single-process store can offer. It is reentrant because the
adapter's compare-and-set commit re-acquires the same lock on the same thread
when the claim commits standalone.

**MySQL/MariaDB, SQL Server, SQLite, Elasticsearch, and other dialects** use the
portable default. MySQL and MariaDB have `SKIP LOCKED` but no
`UPDATE … RETURNING`, so the single-statement form does not compile there; SQL
Server uses `OUTPUT` with different table-hint semantics; SQLite serializes
writers; Elasticsearch is non-relational. PostgreSQL is the only dialect that
offers `FOR UPDATE SKIP LOCKED` and `UPDATE … RETURNING` together, so it is the
sole fast-path dialect. A dedicated MySQL or MSSQL fast path can be added later
(two-statement lock-then-update, or `OUTPUT`) if profiling justifies it.

The MySQL provider shipped on the portable path, as written here. The claim
conformance suite passes against MySQL 8.4 and MariaDB 11.4, and no fast path
was added.

**Transaction boundary.** `_claim` commits the claim through the
DAO's standalone-commit path, so the lock and state change are durable the
moment it returns. It must therefore be called **outside** an active Unit of
Work. Inside a UoW the write would not commit until the UoW does, so other
workers would not see the claim and the lock-then-return guarantee would not
hold. `OutboxProcessor.get_next_batch_of_messages` calls it with no surrounding
UoW, which is correct.

`OutboxRepository.claim_batch(worker_id, limit, target_broker=None)` is the new
public entry point, built on `_claim`, and `OutboxProcessor` uses it.
`OutboxProcessor` now claims once when it fetches the batch, instead of once
per message during processing. `OutboxRepository` is framework-internal
plumbing (not part of the public `protean.*` surface user code builds on), so
no deprecation cycle applies. `claim_for_processing` (the racy per-message
claim that `claim_batch` supersedes) is removed outright, while
`find_unprocessed` is kept as a read-only inspection query alongside its
siblings (`find_failed`, `find_abandoned`,
`find_published`, `find_processing`).

`_claim` adds to the optimistic-concurrency work (epic 5.1,
`BaseDAO._validate_and_update_version`) and replaces none of it. Version
checking guards *aggregate updates* against lost writes, while `_claim` guards
*queue-style claims* against double processing.

Both rely on the same principle: a guarded `UPDATE … WHERE <expected state>` so
the database, not the application, decides the winner. For aggregate updates
the adapter enforces this principle with SQLAlchemy's native
**`version_id_col`**. Protean owns the version value
(`version_id_generator=False`, advanced by `_validate_and_update_version`), and
the ORM flush emits
`UPDATE … SET …, _version = <new> WHERE id =:id AND _version = <loaded>`.
The flush raises `StaleDataError` (translated to `ExpectedVersionError` at
commit) when a concurrent write already advanced the version. The adapter uses
`version_id_col` instead of issuing an eager
`UPDATE … WHERE _version =:expected` because the SQLAlchemy provider runs an
**AUTOCOMMIT engine**. The UnitOfWork achieves atomicity by deferring every
write to a single flush at commit, so an eager statement would autocommit
mid-UoW and break transaction isolation and rollback. The version predicate
runs inside the deferred flush. The guard is therefore atomic without a serial
isolation level, and the write stays invisible until commit. A non-atomic
read-compare-write (read the version in Python, compare, then write
unconditionally) would *not* hold: two transactions can both read the same
version and both write, silently losing one update, which is the failure the
guarded `UPDATE` prevents.

> **Superseded in part by ADR-0027.** The AUTOCOMMIT engine described above was
> later removed. As of ADR-0027 a Unit of Work is one real database transaction,
> so `version_id_col` no longer guards against an eager statement autocommitting
> mid-UoW; it is now part of the UoW's real flush. The optimistic-concurrency
> contract in this ADR is unchanged. Only the transaction-model justification
> above is superseded.

**The aggregate root is the concurrency boundary, including child changes.**
The version guard above protects the root's own fields, but an aggregate can be
modified purely through a child entity (a `HasMany`/`HasOne` member). An
example is a change to a line item's quantity, with no root-field change and no
event. Such a change persists the child through the un-versioned path
(`_update(expected_version=None)`). A child entity is not an aggregate, so
`_validate_and_update_version` does not run for it. `Repository._do_add`
re-saves the root only when the root itself is new or changed. A child-only
change would therefore leave the root's version untouched. Two concurrent
child-only updates would then both succeed, which is the child counterpart of
the lost update above. We treat the aggregate root as the unit of concurrency
control: `Repository._do_add` re-saves the root not only when the root's own
fields changed but also when any persisted child was directly edited
(`_has_changed_child`, which mirrors the direct-update detection already in
`_sync_children`), so the guarded root save runs and advances `_version`. This
covers a child's scalar, value-object, and reference fields uniformly, because
the check reads the child's own `state_.is_changed` rather than the field kind.
Under a transactional provider the child writes and the root version bump
commit together in the Unit of Work.

Adding or removing a `HasMany` child through the `add_`/`remove_` collection
methods is deliberately out of scope: those methods do not mark the root
changed, `mark_changed` no-ops while a freshly added child is new (so it does
not trip `_has_changed_child`), and concurrent adds of distinct children do not
race the way concurrent edits of the same existing data do. Assigning or
replacing a `HasOne` child (`aggregate.child = ...`) is different. It goes
through the root's own `__setattr__`, marks the root changed, and is
version-guarded like any root-field change.

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
- The "already claimed" contention messages in the log disappear on the fast
  path. Workers never select rows they cannot claim.
- Because the claim now happens once at batch fetch (not per message), a worker
  that dies after claiming but before publishing leaves the **whole claimed
  batch** in `processing` until `locked_until` expires. The eligibility
  criteria include `PROCESSING` rows whose lock has expired, so workers then
  reclaim those rows automatically. The criteria still exclude an
  actively-locked `PROCESSING` row, so no worker takes over an in-flight
  message. The batch claim leaves a wider stall window than the previous
  per-message claim (which left only the in-flight message stuck), but delivery
  is still at-least-once and self-healing. Size `locked_until` against
  `messages_per_tick` and expected processing time.
- New adapters get correct behaviour from the portable default at no extra
  cost. Implementing the fast path is an opt-in optimization.
- The fast path depends on the SQL backend supporting `SKIP LOCKED` and
  `RETURNING`. The dialect allow-list (`_SKIP_LOCKED_DIALECTS`) keeps the
  decision explicit; an unlisted dialect silently and correctly uses the
  portable default.

## Alternatives Considered

- **Ship only the portable default**: Rejected. It is the same `1 + N` cost as
  today, and cutting round trips is the purpose of this change.
- **`SELECT … FOR UPDATE SKIP LOCKED` followed by a separate `UPDATE`**:
  rejected, because testing showed double-claims: the row locks taken by the
  `SELECT` were not reliably held across the Python round trip to the separate
  `UPDATE`. This approach also still takes two statements. The single
  `UPDATE … RETURNING` with the locking sub-select is atomic, so no window
  opens between the lock and the claim.
- **Hand-rolled raw SQL per dialect (CTEs, `OUTPUT` for MSSQL, two-statement
  for MySQL).** Rejected for now: PostgreSQL renders the whole claim from one
  SQLAlchemy Core construct (`UPDATE … FOR UPDATE SKIP LOCKED … RETURNING`),
  and that construct is far less to maintain and get wrong. PostgreSQL is also
  the dialect most likely to run a high-throughput outbox. MySQL/MariaDB (no
  `UPDATE … RETURNING`) and MSSQL (`OUTPUT` + different table hints) would each
  need custom SQL, so they use the portable default for now. If profiling
  justifies them, Protean can add dedicated fast paths later.
- **Put dialect dispatch in `OutboxRepository`**: Rejected. The contract is
  broader than the outbox and belongs at the DAO layer where other consumers
  can reuse it.

## Amendment (October 2026): hold-back

The outbox needs a partition key's rows published in commit order
(ADR-0028, outbox-side ordering amendment). A plain `criteria` filter cannot
express that, because whether a row may be claimed depends on other rows.

**Amended decision:** `_claim` takes an optional `hold_back: HoldBack`. When it
is `None`, the claim behaves as described above. When it is set, a row that
matches `hold_back.applies` belongs to a group: the rows with equal
`hold_back.group_by` fields, in the same entry of `hold_back.lanes`. Such a row
is claimed only when every earlier row of its group (by `hold_back.order`)
that matches `hold_back.holds` is claimed in the same call. Rows that do not
match `applies` are claimed as before.

Held rows must not fill the batch, or a halted group with more rows than
`limit` would keep every other group from being claimed.

- **PostgreSQL** keeps one statement. A `MATERIALIZED` CTE selects and locks
  the candidates with `FOR UPDATE SKIP LOCKED`. A grouped row is a candidate
  only when every earlier holding row of its group matches `criteria` and
  sorts before it in the claim order, so held rows rarely enter the `LIMIT`.
  A row another transaction has locked can still take a slot before
  `SKIP LOCKED` drops it.
  The outer `UPDATE` claims a candidate only when no earlier holding row of
  its group sits outside the CTE, which covers rows another worker has
  locked.
- **The portable default** reads candidates a page at a time, `limit` rows per
  page, until the batch is full or the rows run out. For each grouped
  candidate it queries for an earlier holding row of the group that this call
  has not claimed. Once a group has a held row, its later rows in the call are
  skipped. There is no cap on the scan, because a cap would let a halted
  group starve the others. Pages come from `_claim_candidates`. The SQL
  adapter's version adds the same candidate filter as the PostgreSQL
  statement, so on SQLite, MySQL, MariaDB and SQL Server a halted group's
  backlog never enters a page. The base version of `_claim_candidates` reads
  held rows too. On an adapter that does not override it, a large halted
  backlog therefore costs one page read per `limit` held rows on every call.
- **The memory adapter** runs the portable default under its lock, as before.
