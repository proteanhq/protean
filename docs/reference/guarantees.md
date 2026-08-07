# Consistency & Delivery Guarantees

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

This page states, per port and per adapter, what Protean promises for **ordering**,
**delivery**, **consistency**, and the **isolation** it assumes. It is the
normative contract: conformance and property tests cite a row here as their
expected behavior, and the correctness fixes in the framework are described in
terms of the guarantee they restore.

A guarantee is only what is listed here. Where an adapter happens to be stronger
than its port requires (for example, one backend returning rows in a stable order
without an explicit `order_by`), that extra behavior is noted but is **not** part
of the contract and may change.

## How to read this page

Not every dimension applies to every port; each table shows only the relevant
ones, and may fold two into one column (for example *OCC & consistency*). The
dimensions:

- **Ordering** — the order in which writes become visible or messages are
  delivered. *Per-stream* order is within a single aggregate stream (or queue);
  *global* order is across streams.
- **Delivery** — how many times a write or message takes effect.
  - *At-least-once*: delivered one or more times; a consumer may see duplicates
    (on crash/retry) and must tolerate them.
  - *At-most-once (best-effort)*: delivered zero or one time; on failure it may be
    lost and is **not** redelivered.
  - *Exactly-once-effect*: duplicates may still be delivered, but an idempotency
    mechanism ensures the *effect* applies once. Protean never promises
    exactly-once *delivery* — only exactly-once *effect*, and only where opted in.
- **Consistency** — when a write is visible to a later read. *Read-your-writes*:
  a reader that made a write sees it on a subsequent read. *Eventual*: the write
  becomes visible after some delay.
- **Isolation / concurrency model** — the database isolation level, or the
  concurrency-control mechanism, under which the guarantee holds.

A few terms used below: the **outbox** is the table a Unit of Work writes
committed messages into for reliable post-commit dispatch; the **recovery stream**
is where a subscription records a failed position for later retry; the
**idempotency store** is the (Redis-backed) store that dedups commands by
`idempotency_key`.

Optimistic concurrency (**OCC**) throughout means: an aggregate carries a
`_version`; an update asserts the expected version atomically with the write and
raises `ExpectedVersionError` if it has moved. See
[ADR-0013](../adr/0013-optimistic-concurrency-and-claim-contract.md).

---

## Aggregate persistence (repository / DAO)

A repository persists an aggregate through a Unit of Work. The aggregate root is
the concurrency boundary
([ADR-0013](../adr/0013-optimistic-concurrency-and-claim-contract.md)): OCC is
enforced on both write paths — `repository.add` (which routes through the DAO's
`save()`) and the DAO's `update()` (which now persists through `save()` too) — on
the root's `_version`.

!!! note "Child changes are guarded through the root, not independently"
    **Child-entity changes within a collection** are not independently
    version-guarded. By ADR-0013 the aggregate root is the concurrency boundary,
    so a concurrent collection add/remove or child-field change is detected only
    if it also advances the *root's* `_version`.

| Adapter | Ordering (no `order_by`) | Write atomicity / visibility | OCC & consistency | Isolation / concurrency model |
|---|---|---|---|---|
| **Memory** | Insertion order (not a promise) | Copy-on-write session; visible at commit; `rollback()` discards the session's pending changes | Real OCC: commit is a compare-and-set that re-checks the version against the live store under the provider lock and merges per record; a stale write raises `ExpectedVersionError` (see below) | Single process; per-provider lock (no MVCC) |
| **SQLAlchemy** (PostgreSQL / MSSQL) | No guaranteed order | One real transaction per UoW (read-committed engine, `autoflush=True`, [ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)); all writes commit or roll back atomically, and an in-UoW read sees the UoW's own pending writes | OCC via `version_id_col` → `UPDATE … WHERE _version = :expected`; a zero-row match raises `ExpectedVersionError` | **READ COMMITTED or stronger** (see below) |
| **SQLAlchemy** (SQLite) | No guaranteed order | Session autoflushes; write visible in-session | Same `version_id_col` OCC | Writers serialized; a contended write raises `SQLITE_BUSY` (no READ COMMITTED level) |
| **Elasticsearch** | No guaranteed order | No multi-document transaction; each write forced `refresh=True` | OCC via `if_seq_no` / `if_primary_term`; a 409 conflict raises `ExpectedVersionError` | None (no transactions) |

**Consistency (read-your-writes).** Within a Unit of Work, every repository *on a
given provider* shares one session, and a read sees the UoW's own uncommitted
writes.

- **Memory / SQLite** — all reads see the UoW's own uncommitted writes.
- **PostgreSQL / MSSQL**: the UoW is a real transaction with `autoflush=True`
  ([ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)), so all reads
  (`filter` / `count` / `exists` / `get`) inside the UoW see the UoW's own pending
  writes, and in-UoW uniqueness validation sees them too. On a rollback none of it
  persists.
- **Elasticsearch** — has no session isolation: every write lands immediately
  (`refresh=True`) and is **not** rolled back, so read-your-writes (both `get` and
  criteria) is trivially satisfied, but a rolled-back UoW's writes persist and are
  visible to others.

Across UoW boundaries, relational adapters see only committed state.

!!! note "UoW atomicity on PostgreSQL/MSSQL"
    Each UoW is one real database transaction
    ([ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)), so its
    relational writes commit or roll back as a unit: a childless aggregate, a
    child-bearing aggregate (parent and children together), and several aggregates.
    A rollback leaves nothing behind (no orphaned parent). The transactional outbox
    row is saved on the same session as the domain write and committed by the same
    `session.commit()`, so the two are atomic (the cross-table test exercises that
    two-table shape). For an event-sourced aggregate the event-store append is a
    separate durable anchor written before the relational commit, so it is outside
    this transaction (ADR-0015). The guarantees are pinned by
    `tests/adapters/repository/sqlalchemy_repo/postgresql/test_postgresql_uow_atomicity_and_ryw.py`
    and its MSSQL mirror.

!!! note "Nested Units of Work"
    A `UnitOfWork` started while another is already active on the same context
    joins the outermost transaction rather than opening its own (there are no
    savepoints). Only the outermost UoW commits or rolls back, and a nested rollback
    rolls back the whole transaction. This holds on every adapter. See
    [ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md).

**Memory OCC holds under concurrent sessions.** Each session still works on a
deep-copied snapshot, but commit is no longer a wholesale replacement: it is a
compare-and-set. Under the per-provider lock, `MemorySession.commit` re-checks
each aggregate's `_version` against the *live* store and then merges only the
records this session changed, key by key. So two overlapping sessions that both
passed the snapshot check no longer both win — the second commit finds the
version already moved and raises `ExpectedVersionError`, and sessions writing
*different* records never clobber each other. This holds on the same
version-guarded write paths as every adapter (`repository.add` and the DAO's
`update()`, both through `save()`), with the same root-boundary caveat above
(independent child changes are guarded only through the root's version). Memory
is still a single-process test/dev store (no MVCC, no cross-process
coordination), but on that path its no-lost-update behavior now matches a real
database, so aggregate-level concurrency tests can run against it.

**Ordering.** A query without an explicit `order_by` has **no guaranteed order**.
Some adapters are incidentally stable (SQLAlchemy appends `ORDER BY <pk> ASC`,
Memory preserves insertion order); do not rely on it — pass `order_by`.

**Isolation (the OCC floor).** On PostgreSQL / MSSQL the lost-update fix
([ADR-0013](../adr/0013-optimistic-concurrency-and-claim-contract.md)) relies on
the write being a single conditional `UPDATE` whose `WHERE _version = :expected`
predicate is re-evaluated under the row lock against committed state. That is
atomic at **READ COMMITTED**, the default on both; Protean runs the engine at
read-committed ([ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)) and
requires nothing stronger. Running below READ COMMITTED is unsupported. SQLite has no READ COMMITTED level: it serializes writers and a
contended write raises `SQLITE_BUSY` rather than losing one.

**Claim / concurrent-consume.** For queue-style claiming (e.g. the outbox), the
`_claim` contract (ADR-0013) guarantees no double-claim. PostgreSQL uses a
`SELECT … FOR UPDATE SKIP LOCKED` fast path; every other backend uses a portable
guarded read-then-update (same no-double-claim guarantee, but blocking, not
skipping). Elasticsearch is not recommended as a concurrently-consumed claim store
(a lost race surfaces as a version conflict).

---

## Event store

The event store is the source of truth for event-sourced aggregates. `append`
writes one message at a time, forwarding the aggregate's `expected_version` for
an atomic OCC check. Reads follow the read-position contract
([ADR-0024](../adr/0024-event-store-read-position-contract.md)): a specific
stream pages by its per-stream `position`; a category or `$all` read pages by
`global_position`, **inclusive**, ascending.

| Adapter | Per-stream order | Global / `$all` order | Append & OCC | Consistency |
|---|---|---|---|---|
| **Memory** | Gapless per-stream `position`, ascending | `global_position` ascending; no gaps (single process, no rollback) | Version check + append atomic under a class lock (conflict raises) **for single-threaded use**. When the append is deferred into an enclosing Unit of Work it publishes after that class lock is released, so overlapping UoWs on the same stream are not serialized — do not rely on the Memory event store under concurrent writers | Read-your-writes (in process); single-writer test/dev store |
| **MessageDB** | Gapless per-stream `position`, ascending | `global_position` ascending, strictly increasing. **Globally** it may contain gaps — a rolled-back append permanently consumes a value. **Within a single category it is gap-free**: MessageDB serializes same-category writes with a per-category advisory lock held to commit. | `write_message(… expected_version)` stored proc; conflict raises | Read-your-writes (committed before `append` returns) |

**Append is per message.** A Unit of Work that raises N events performs N
individual OCC-guarded appends; they are not a single atomic batch. The event-store
append is the durable anchor of the commit sequence, and the relational/outbox
commit follows it non-atomically.

!!! note "Interim — not yet a stable contract"
    The cross-store atomicity story
    ([ADR-0015](../adr/0015-event-store-append-as-durable-anchor.md)) is marked
    *Proposed*: the window between the event-store append and the relational/outbox
    commit is closed by a reconciliation sweep on startup (internal outbox rows are
    rebuilt from the event store; external-broker rows are not). Treat this as
    interim; it may change.

---

## Subscriptions & delivery

A domain event/command is dispatched either **synchronously** (inline at commit)
or **asynchronously** (a background subscription reads it from the event store).
The two differ on every dimension:

| | Synchronous | Asynchronous |
|---|---|---|
| **When it runs** | Inline, after the commit | Background engine, after the event is durable |
| **Delivery** | At-most-once (no retry) | At-least-once |
| **Ordering** | Breadth-first chain order (ADR-0016) | Per-category contiguous `global_position`; `$all` in `global_position` order |
| **Consistency** | Read-your-writes for the projection | Eventual |
| **Retry / recovery** | None | Retried up to `max_retries` on a recovery pass |
| **Terminal state** | Propagates to the caller | `Exhausted` — position dropped, no DLQ |

The defaults quoted below (`position_update_interval` 10, `max_retries` 3,
`recovery_interval_seconds` 30, `gap_timeout_seconds` 5) are the base profile;
server profiles may override them. The nuances follow.

**Synchronous handlers** run inline at commit time, breadth-first
([ADR-0016](../adr/0016-breadth-first-synchronous-event-dispatch.md)), and are not
re-delivered here. They execute **after** the aggregate write has committed,
**at-most-once**, with no retry: a synchronous handler failure does not roll back
the already-committed write and propagates to the caller (as `TransactionError`,
or `ExpectedVersionError` for a version conflict).

**Asynchronous delivery is at-least-once by default.** The read cursor advances
after a message is handled, *including on failure* (the failure is first recorded
to a recovery stream, then retried by a periodic pass, rather than blocking the
subscription on a poison message). The cursor is checkpointed durably but in
batches (every `position_update_interval` messages, 10 by default), so a crash
re-delivers up to that many messages. Handlers must tolerate duplicates.

**Failure handling and terminal state.** A failed message is retried up to
`max_retries` (default 3) on a `recovery_interval_seconds` cadence (default 30).
On exhaustion the position is marked **`Exhausted`** and dropped from tracking (a
`handler.failed` event is emitted) — there is **no dead-letter queue for
event-store subscriptions**; a DLQ applies only to broker/stream subscriptions.

!!! note "Recovery of a failed message is crash-safe"
    With recovery enabled (the default), the failure is recorded to the recovery
    stream *before* the read cursor advances past it. The record is written per
    message while the cursor's durable checkpoint is batched, so the record is
    always durable before the cursor is durably flushed past the position. That
    closes the drop window two ways:

    - If the recovery write itself fails, it raises before the cursor advances, so
      the message is re-read and retried on the next poll.
    - If the record is written and the process then crashes, the durable cursor is
      either still behind the position (the message is re-read) or already past it
      (the durable record is picked up by the recovery pass) — never dropped.

    With `enable_recovery=False` a failed message is intentionally dropped (no
    tracking, no retry). This is separate from the batched-checkpoint at-least-once
    property for the happy path, where a crash re-delivers the last unflushed batch.

**Exactly-once-effect is opt-in**, in two places:

- A projector marked `@domain.projector(idempotent=True)` on a relational provider
  records `(message_id, handler)` in the same transaction as the read-model write,
  so a redelivered message is a no-op
  ([ADR-0017](../adr/0017-consume-side-idempotency-for-projectors.md)). On the
  in-memory provider it degrades to dedup by last-processed message id — it
  protects against **serial** redelivery only, not concurrent delivery. Markers
  are pruned after a retention window (default 7 days); a redelivery after the
  window re-applies.
- A command carrying an `idempotency_key` is deduped against the idempotency store,
  **only when that store is active** (Redis-backed); otherwise the key is not
  enforced. Dedup is time-bounded: success entries expire after 24 h, error
  entries after 60 s (so a failed command becomes retryable sooner).

**Read-model consistency.** Under synchronous processing, projectors run inline at
commit, so a read model is updated before `domain.process()` returns
(read-your-writes for the projection). Under asynchronous processing the read
model updates via the **event-store subscription** path (event store →
subscription → projector) and is **eventually** consistent. (The outbox is not
involved in internal projector delivery; it publishes to external brokers.)

**Ordering.** A per-category subscription delivers in `global_position`-ascending,
contiguous order, which preserves each stream's order (a category is gap-free per
the per-category advisory lock above). A `$all` subscription delivers in
`global_position`-ascending order — this is **assignment order, not cross-category
commit or causal order**; only per-category order is preserved.

**No silent skip for `$all`.** Because a lower `global_position` can commit *after*
a higher one across categories, a naive "advance past the highest seen" cursor
could permanently skip a late-committing position. A `$all` subscription instead
processes only the contiguous run from its cursor, **holds at the first gap**, and
advances the cursor past a hole only *after* the batch is processed
([ADR-0025](../adr/0025-all-subscription-gap-safety.md)). A gap that does not fill
within `gap_timeout_seconds` (default 5) is assumed rolled back and abandoned —
**logged, not silent**. The guarantee is therefore: **no committed `$all` event is
silently skipped; a genuinely slow commit (> `gap_timeout_seconds`) is logged and
dropped.** Single-category subscriptions are gap-free by construction and run none
of this machinery.

**Single writer.** Event-store subscriptions have no cluster-wide ownership;
Protean refuses to start more than one worker when an event-store subscription is
registered — **unless the operator sets `acknowledge_event_store_risk`** (an
explicit opt-out). The guard is best-effort: if the domain cannot be classified at
startup it defers to the workers rather than refusing. Horizontal scaling of a
handler is done with a stream subscription (Redis consumer groups), below.

---

## Outbox (transactional delivery to brokers)

When a Unit of Work commits, published messages are written to the outbox in the
same transaction; an outbox processor then claims and publishes them to the
broker. This decouples the domain commit from broker availability.

| Dimension | Guarantee |
|---|---|
| **Delivery** | At-least-once to the broker: a crash after `broker.publish` but before the row is marked published re-delivers. |
| **Terminal state** | After `max_retries` (default 3) with exponential backoff, a message is marked **`abandoned`** (`OutboxStatus.ABANDONED`) — permanently *not* delivered, retained for observability, cleaned up after a retention period. |
| **Dedup** | Write-side idempotency on `(message_id, target_broker)`; a published event is written once per configured external broker. |
| **Ordering** | Claimed **by priority**, not per-stream/commit order — a higher-priority later message can overtake a lower-priority earlier one, and same-priority order is database-dependent. Do not assume end-to-end FIFO through the outbox. |
| **Crash recovery** | A startup sweep rebuilds missing *internal* outbox rows from the event store (ADR-0015); external-broker rows are not reconciled. |

---

## Broker (external messaging)

Brokers carry messages to external subscribers. Capability tiers gate what a broker
promises; a lower-tier broker returns empty / warns rather than silently faking a
capability it lacks. Within a Unit of Work, `publish` is deferred until after the
DB commit.

| Adapter | Tier | Ordering | Delivery | Durability |
|---|---|---|---|---|
| **Inline** | `reliable_messaging` | Per-stream FIFO *in practice — not advertised, not a contract* | At-least-once — ack/nack with backoff requeue on nack; stale in-flight messages time out to the DLQ; DLQ on exhausted retries | In-process only (non-durable) |
| **Redis PubSub** | `simple_queuing` | Per-stream FIFO *in practice — not advertised, not a contract* | **At-most-once (best-effort)**: no ack/nack; the read advances the consumer position across the whole batch *before* any message is processed, so a crash loses **every not-yet-processed message in that batch** (up to `messages_per_tick`). Concurrent consumers in one group can also duplicate-and-skip (non-atomic read/increment). | Redis-backed state; lost messages are not recoverable |
| **Redis Streams** | `ordered_messaging` | Per-stream FIFO — **guaranteed** (`MESSAGE_ORDERING`, native stream IDs) | At-least-once — `XREADGROUP` pending list, `XACK`, redelivery across restarts | Durable in Redis Streams |

Ordering is a *contract* only where the adapter advertises `MESSAGE_ORDERING`
(Redis Streams). The Inline and PubSub brokers preserve order in practice but do
not advertise it, so cross-adapter code must not depend on it.

End-to-end order for `published` domain events is set by the **outbox** (by
priority — see [Outbox → Ordering](#outbox-transactional-delivery-to-brokers)),
not by commit order; a broker's per-stream FIFO only preserves the order the
outbox published in.

**DLQ differs by adapter.** The Inline broker *populates* a DLQ automatically (on
exhausted retries and on in-flight timeout). The Redis Streams broker provides DLQ
*inspection and replay* over externally-populated `:dlq` streams but does **not**
itself move poison messages to a DLQ (a nacked message stays pending).

**The DLQ move is not lossy on a publish failure.** When the framework routes an
exhausted message to the DLQ, it ACKs the source stream only *after* the DLQ
publish succeeds. If the publish fails, the message is NACKed (after a
`retry_delay_seconds` backoff) and its retry count retained rather than being ACKed
away, so it is redelivered and the DLQ move retried at the retry cadence, not at
poll speed. On **Redis Streams** this repeats until the DLQ recovers. The
**Inline** broker has its own independent retry ceiling; under a *persistent* DLQ
outage that ceiling eventually moves the message to the broker's *native* DLQ
(which the DLQ CLI lists) and stops redelivering, provided the broker's own DLQ is
enabled (the default). So under a DLQ outage the message is not silently dropped.
Disabling a DLQ (`enable_dlq=False`) discards an exhausted message (ACK without a
DLQ move), which is intentional.

---

## Cache

The cache (projections keyed by id, with pattern queries) is a **best-effort,
non-durable** store with per-key TTL (default 300s). It promises no ordering, no
transactions, and no atomic multi-key operations. The Memory cache is in-process
and lost on exit; the Redis cache is durable only to the extent the Redis
deployment is configured to persist.

---

## Guarantees restored by correctness fixes

| Fix | Guarantee restored |
|---|---|
| **#1087** | *No lost update.* The aggregate OCC check is atomic with the write (`UPDATE … WHERE _version = :expected`), so two concurrent updates can no longer both succeed and silently drop one. Holds at READ COMMITTED on PostgreSQL / MSSQL. |
| **#1249** ([ADR-0024](../adr/0024-event-store-read-position-contract.md)) | *Correct read position.* Category and `$all` reads page by `global_position`, inclusive and ordered, uniformly across adapters — the substrate the no-skip guarantee is expressed on. |
| **#1088** ([ADR-0025](../adr/0025-all-subscription-gap-safety.md)) | *No silent skip for `$all`.* A late-committing lower `global_position` is no longer stepped over; the cursor holds at the gap until it fills or times out. |
| **#1258** | *No lost update on the Memory adapter.* `MemorySession.commit` is now a compare-and-set: it re-checks each aggregate's version against the live store under the provider lock and merges only the records it changed, so two concurrent sessions can no longer both succeed and silently drop one. Makes the in-memory adapter a faithful concurrency stand-in (single process, no MVCC). |

---

## Formal verification of the two-phase protocols

The two protocols where these guarantees are hardest to reason about, the `$all`
subscription checkpoint advance and the outbox publish, have machine-checked
TLA+ specifications under [`specs/`](https://github.com/proteanhq/protean/tree/main/specs)
in the repository. TLC explores every interleaving of out-of-order commits, lock
expiry, redelivery, and crash points up to a bound, and asserts the invariants
that state these guarantees. Each invariant maps to a specific row above; the
mapping is in `specs/README.md`. Each spec also carries a revert test that
reintroduces the corresponding bug (#1088 for the checkpoint, mark-before-publish
for the outbox) so the model demonstrably has teeth.

This is design-time verification, not a CI gate: it verifies the design, and is
re-run deliberately when a protocol changes, not on every commit.

---

## Out of scope

- **Cross-bounded-context delivery of `published` events.** Whether a
  `published=True` event carries a delivery guarantee to *external* subscribers is
  not yet settled — the routing mechanism is being refined
  ([ADR-0002](../adr/0002-event-publication-visibility.md), *Proposed*).
- **Horizontal scaling of a single event-store subscription.** Event-store
  subscriptions are single-writer by construction (see *Single writer*); scaling a
  handler across workers uses a stream subscription and Redis consumer groups.
- **Nested Units of Work.** Opening a UoW inside a UoW reuses the in-progress one
  rather than nesting with savepoints; there is no independent inner-commit
  guarantee. Treat a UoW as flat.
- **Email adapters.** The shipped email adapters are fire-and-forget with no
  delivery guarantee, retry, or outbox integration.
