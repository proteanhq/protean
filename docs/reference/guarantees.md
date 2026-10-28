# Consistency and delivery guarantees

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

This page states what Protean promises for each port and adapter: the order in
which writes and messages arrive, how many times they take effect, when a write
becomes visible, and the isolation each promise needs. Conformance and property
tests cite a row here as their expected behavior.

A guarantee is only what this page lists. Where an adapter happens to be
stronger than its port requires (for example, one backend returning rows in a
stable order without an explicit `order_by`), the page says so, and that extra
behavior can change in any release.

## Summary

| Part | Ordering | Delivery and atomicity | Consistency | Concurrency |
|---|---|---|---|---|
| [Aggregate persistence](#aggregate-persistence) | None without `order_by` | One transaction per Unit of Work (relational adapters) | Read-your-writes inside a Unit of Work | OCC on the aggregate root |
| [Event store](#event-store) | Per stream; categories and `$all` by global position | One append per message | Read-your-writes | OCC on the expected version |
| [Subscriptions](#subscriptions-delivery) | Per category; `$all` holds at gaps | Sync: at-most-once. Async: at-least-once | Sync: read-your-writes. Async: eventual | One worker per event-store subscription |
| [Outbox](#outbox) | By priority, then write order | At-least-once to the broker | Eventual | No row claimed twice |
| [Broker](#broker) | FIFO promised only on Redis Streams | At-least-once, except Redis PubSub (at-most-once) | Eventual | Depends on the adapter |
| [Cache](#cache) | None | Best-effort, not durable | No transactions | No atomic multi-key operations |

??? info "Terms used on this page"
    | Term | Meaning |
    |---|---|
    | Per-stream order | Order within one aggregate stream or queue. |
    | Global order | Order across streams. |
    | At-least-once | A message is delivered one or more times. A consumer can see duplicates after a crash or retry and has to tolerate them. |
    | At-most-once | A message is delivered zero or one time. A message lost on failure is not redelivered. |
    | Exactly-once effect | Duplicates can still arrive, but an idempotency check applies the effect once. Protean never promises exactly-once delivery, and offers exactly-once effect only where you opt in. |
    | Read-your-writes | A reader that made a write sees it on a later read. |
    | Eventual | A write becomes visible to readers after some delay. |
    | OCC | Optimistic concurrency control. An aggregate carries a `_version`, an update asserts the expected version in the same step as the write, and a stale write raises `ExpectedVersionError`. See [ADR-0013](../adr/0013-optimistic-concurrency-and-claim-contract.md). |
    | Outbox | The table a Unit of Work writes outgoing messages into, in the same transaction as the domain write, for dispatch after the commit. |
    | Recovery stream | Where a subscription records a failed message's position for a later retry. |
    | Idempotency store | The Redis-backed store that deduplicates commands by `idempotency_key`. |

---

## Aggregate persistence

A repository saves an aggregate through a Unit of Work. The aggregate root is
the concurrency boundary
([ADR-0013](../adr/0013-optimistic-concurrency-and-claim-contract.md)), so OCC
checks the root's `_version` on both write paths: `repository.add` and the
DAO's `update()`, which both persist through `save()`.

| Adapter | Ordering without `order_by` | Atomicity | OCC check | Isolation |
|---|---|---|---|---|
| **Memory** | Insertion order, not promised | Copy-on-write session, visible at commit | Compare-and-set at commit | One process, per-provider lock |
| **PostgreSQL, MSSQL, MySQL, MariaDB** | None | One transaction per Unit of Work | Conditional `UPDATE … WHERE _version = :expected` | READ COMMITTED |
| **SQLite** | None | Autoflushed session | Conditional `UPDATE`, as above | Writers serialized |
| **Elasticsearch** | None | None: each write lands at once | `if_seq_no` / `if_primary_term` | None |

### Read-your-writes

Within a Unit of Work, every repository on one provider shares a session, and
a read sees the Unit of Work's own uncommitted writes. On the relational
adapters this covers `filter`, `count`, `exists` and `get`, and uniqueness
validation inside the Unit of Work. A rollback discards all of it. Across Units
of Work, the relational adapters show only committed state.

### No lost update

Two concurrent updates to one aggregate cannot both succeed. On the relational
adapters the version check and the write are one conditional `UPDATE`, which is
atomic at READ COMMITTED. Protean opens every engine at READ COMMITTED
([ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)), including
MySQL and MariaDB, whose own default is REPEATABLE READ. Running below READ
COMMITTED is unsupported. SQLite has no READ COMMITTED level: it serializes
writers, and a contended write raises `SQLITE_BUSY`. On Memory, commit
re-checks each aggregate's version against the live store under the provider
lock, so aggregate-level concurrency tests can run against it.

### No double claim

For queue-style claiming, such as the outbox, the `_claim` contract (ADR-0013)
claims each row once. PostgreSQL uses `SELECT … FOR UPDATE SKIP LOCKED`. Every
other backend uses a guarded read-then-update, which gives the same guarantee
but blocks where PostgreSQL skips.

### Known exceptions {#persistence-exceptions}

- **Child entities**: A change to a child entity is caught by OCC only if it
  also advances the root's `_version`. Children are not versioned on their own.
- **Elasticsearch**: Has no transactions. Writes land immediately and are not
  rolled back, so a rolled-back Unit of Work's writes stay visible to others. A
  lost claim race surfaces as a version conflict, so Elasticsearch is not
  recommended as a claim store.
- **Memory**: A single-process test and development store, with no
  cross-process coordination.
- **Nested Units of Work**: A Unit of Work started inside another joins the
  outer transaction. There are no savepoints, so a nested rollback rolls back
  the whole transaction. This holds on every adapter.
- **Ordering**: SQLAlchemy appends `ORDER BY <pk> ASC` and Memory keeps
  insertion order. Neither is part of the contract. Pass `order_by`.

??? note "How this holds"
    On PostgreSQL, MSSQL, MySQL and MariaDB each Unit of Work is one database
    transaction ([ADR-0027](../adr/0027-unit-of-work-is-a-real-transaction.md)),
    with `autoflush=True`. A childless aggregate, a parent with its children,
    and several aggregates all commit or roll back as a unit, and a rollback
    leaves no orphaned parent. The outbox row is saved on the same session and
    committed by the same `session.commit()` as the domain write. For an
    event-sourced aggregate the event-store append is written before the
    relational commit, outside this transaction (ADR-0015).
    `tests/adapters/repository/sqlalchemy_repo/postgresql/test_postgresql_uow_atomicity_and_ryw.py`
    and its MSSQL mirror pin these guarantees.

    On Memory each session works on a deep copy. At commit, under the
    per-provider lock, `MemorySession.commit` compares each aggregate's
    `_version` with the live store and merges only the records the session
    changed. The second of two overlapping sessions raises
    `ExpectedVersionError`, and sessions that write different records do not
    overwrite each other.

---

## Event store

The event store is the source of truth for event-sourced aggregates. Reads
follow the read-position contract
([ADR-0024](../adr/0024-event-store-read-position-contract.md)): a stream pages
by its per-stream `position`, and a category or `$all` read pages by
`global_position`, inclusive and ascending.

| Adapter | Per-stream order | Global order | Append and OCC | Consistency |
|---|---|---|---|---|
| **Memory** | Gapless `position` | `global_position`, no gaps | Atomic under a class lock, single-threaded use only | Read-your-writes, in process |
| **MessageDB** | Gapless `position` | `global_position`, gap-free within a category | `write_message` stored procedure with `expected_version` | Read-your-writes once `append` returns |

### Known exceptions {#event-store-exceptions}

- **Append is per message**: A Unit of Work that raises several events makes
  one OCC-checked append per event. They are not one atomic batch.
- **MessageDB global gaps**: A rolled-back append uses up its
  `global_position`, so positions across categories can have gaps. Within one
  category there are none, because MessageDB holds a per-category advisory
  lock until commit.
- **Memory with concurrent writers**: An append deferred into an enclosing
  Unit of Work publishes after the class lock is released, so overlapping Units
  of Work on one stream are not serialized. Use it with one writer.

!!! warning "Interim: not yet a stable contract"
    The event-store append is written first, and the relational and outbox
    commit follows it without a shared transaction. The window between them is
    closed by a reconciliation sweep at startup: when the newest event has lost
    its internal outbox row, the sweep rebuilds the rows of every recent event
    that lost one, including the external-broker rows of a `published` event.
    [ADR-0015](../adr/0015-event-store-append-as-durable-anchor.md) is still
    *Proposed*, and this behavior can change.

---

## Subscriptions & delivery

A domain event or command is handled either synchronously, inline at commit, or
asynchronously, by a background subscription that reads it from the event
store.

| | Synchronous | Asynchronous |
|---|---|---|
| **When it runs** | Inline, after the commit | Background engine, after the event is durable |
| **Delivery** | At-most-once, no retry | At-least-once |
| **Ordering** | Breadth-first chain order ([ADR-0016](../adr/0016-breadth-first-synchronous-event-dispatch.md)) | Per category by `global_position`; `$all` by `global_position` |
| **Consistency** | Read models updated before `domain.process()` returns | Eventual |
| **Retry** | None | Up to `max_retries` on a recovery pass |
| **Terminal state** | The error reaches the caller | `Exhausted`: position dropped, no dead-letter queue |

The defaults below (`position_update_interval` 10, `max_retries` 3,
`recovery_interval_seconds` 30, `gap_timeout_seconds` 5) belong to the base
profile. Server profiles can override them.

### Synchronous handlers

A synchronous handler runs once, after the aggregate write has committed. Its
failure does not roll back that write. The error reaches the caller as
`TransactionError`, or as `ExpectedVersionError` for a version conflict.

### Asynchronous delivery

The read cursor advances after each message, including a failed one, whose
failure is first recorded to the recovery stream. The cursor is saved every
`position_update_interval` messages, so a crash re-delivers up to that many.
Handlers have to tolerate duplicates. Read models update through the
event-store subscription; the outbox only publishes to external brokers.

### Failure handling

A failed message is retried up to `max_retries` times, every
`recovery_interval_seconds`. After the last retry its position is marked
`Exhausted`, dropped from tracking, and a `handler.failed` event is emitted.
Event-store subscriptions have no dead-letter queue. Broker and stream
subscriptions do; see [Dead-letter queues](#dead-letter-queues).

### Recovery of a failed message is crash-safe

With recovery on (the default), a crash never drops a failed message: the
failure is recorded to the recovery stream before the cursor moves past it.
With `enable_recovery=False`, a failed message is dropped on purpose, with no
tracking and no retry.

??? note "How this holds"
    The failure record is written per message, and the cursor is saved in
    batches, so the record is always durable before the saved cursor passes
    the message. Two failure cases follow:

    - **The record write fails**: It raises before the cursor advances, and the
      next poll reads and retries the message.
    - **The process crashes after the record is written**: The saved cursor is
      either behind the message, which is then read again, or past it, and then
      the recovery pass finds the record.

    `specs/Recovery.tla` model-checks this protocol. See
    [How the guarantees are checked](#how-the-guarantees-are-checked).

### Exactly-once effect

You can opt in at two places:

- **Projectors**: `@domain.projector(idempotent=True)` on a relational
  provider records `(message_id, handler)` in the same transaction as the
  read-model write, so a redelivered message has no effect
  ([ADR-0017](../adr/0017-consume-side-idempotency-for-projectors.md)). On the
  in-memory provider it deduplicates by the last processed message id. It
  covers redelivery one after another and does not cover concurrent delivery.
  Markers are pruned after a retention window (7 days by default), and a
  redelivery after that is applied again.
- **Commands**: A command with an `idempotency_key` is deduplicated against
  the idempotency store, and only when that store is active. Successful entries
  expire after 24 hours and failed ones after 60 seconds, so a failed command
  can be retried sooner.

### Subscription ordering

A category subscription delivers in ascending, contiguous `global_position`
order, which keeps each stream in order. A `$all` subscription delivers in
ascending `global_position` order. That is the order positions were assigned.
Commit order and causal order across categories are not preserved.

### No silent skip for `$all`

No committed `$all` event is skipped without a log entry. Across categories a
lower `global_position` can commit after a higher one, so a `$all`
subscription processes only the contiguous run from its cursor and holds at
the first gap ([ADR-0025](../adr/0025-all-subscription-gap-safety.md)). A gap
that stays open for `gap_timeout_seconds` is treated as a rollback: the
subscription logs it and moves on. A commit slower than that timeout is
therefore logged and dropped. Single-category subscriptions have no gaps and
skip this check.

### Single writer

Event-store subscriptions have no cluster-wide owner, so Protean refuses to
start a second worker while one is registered. The operator can override this
with `acknowledge_event_store_risk`. If the domain cannot be classified at
startup, the check lets the workers start. To scale a handler across workers,
use a stream subscription with Redis consumer groups.

---

## Outbox

When a Unit of Work commits, its published messages are written to the outbox
in the same transaction. An outbox processor then claims them and publishes
them to the broker, so the domain commit does not depend on the broker being
up.

| Dimension | Guarantee |
|---|---|
| **Delivery** | At-least-once to the broker |
| **Ordering** | By priority, then write order within a priority |
| **Deduplication** | One row per `(message_id, target_broker)` |
| **Terminal state** | `abandoned` after `max_retries` (default 3) with exponential backoff |
| **Crash recovery** | A startup sweep rebuilds missing internal rows from the event store |

### Outbox ordering

Rows are claimed by priority first, so a later message with a higher priority
can overtake an earlier one. Within a priority, rows are claimed by
`created_at` (when the Unit of Work built the row, just before the commit) and
then by the event's position in its commit. One aggregate's events therefore
go out in commit order.

A retried row, a second worker, host clocks that disagree or step back, and
the `DATETIME` rounding (about 3 ms) of a SQL Server outbox table created
before 0.19 and [not converted](migration/v0-19.md#sql-server-stores-datetime-as-datetime2)
can still publish events out of that order, so end-to-end FIFO through the
outbox is not promised.

A category partitioned with
[`sequential_by`](server/sequential-by.md#how-the-outbox-keeps-a-key-in-order)
keeps a key's rows in write order for each target broker and priority lane.
That is commit order for one aggregate instance, but not always across several
instances that share a key. A later row is claimed only when every earlier row
of its key is published or claimed in the same call. An earlier row that is in
flight or failed holds the key, and an abandoned row halts it until an
operator retries or discards the row (`protean outbox retry` or
`protean outbox discard`).

### Known exceptions {#outbox-exceptions}

- **Redelivery**: A crash after `broker.publish` and before the row is marked
  published delivers the message again.
- **Abandoned rows**: An `abandoned` row (`OutboxStatus.ABANDONED`) is never
  delivered. It is kept for inspection and cleaned up after a retention
  period, except a row with a partition key, which stays because it halts its
  key.
- **Crash recovery limits**: The sweep rebuilds one row per configured
  external broker for a `published` event, but only when the event's internal
  row is also missing. External rows lost on their own are not rebuilt, and
  events older than the outbox cleanup retention are skipped (ADR-0015).

---

## Broker

Brokers carry messages to external subscribers. Inside a Unit of Work,
`publish` waits until after the database commit. Each broker declares a
capability tier (Inline is `reliable_messaging`, Redis PubSub is
`simple_queuing`, Redis Streams is `ordered_messaging`), and a broker without a
capability returns empty or warns.

| Adapter | Ordering | Delivery | Durability |
|---|---|---|---|
| **Inline** | Per-stream FIFO in practice, not promised | At-least-once, with ack, nack and backoff | In process only |
| **Redis PubSub** | Per-stream FIFO in practice, not promised | At-most-once | Lost messages cannot be recovered |
| **Redis Streams** | Per-stream FIFO, promised (`MESSAGE_ORDERING`) | At-least-once, through the `XREADGROUP` pending list and `XACK` | Durable in Redis |

### Broker ordering

Ordering is part of the contract only where the adapter advertises
`MESSAGE_ORDERING`, which today is Redis Streams. Code meant to run on any
broker cannot depend on Inline or PubSub order. For `published` domain events
the outbox sets the end-to-end order (see [Outbox ordering](#outbox-ordering)),
and the broker keeps the order the outbox published in.

### Known exceptions {#broker-exceptions}

- **Redis PubSub batch loss**: The consumer position advances across a whole
  batch before any message in it is processed, so a crash loses every
  unprocessed message in the batch (up to `messages_per_tick`). Concurrent
  consumers in one group can also duplicate one message and skip another.
- **Inline durability**: Messages live in the process and are lost when it
  exits.

### Dead-letter queues

The subscription owns retry and dead-lettering for the stream it consumes
([ADR-0042](../adr/0042-subscription-owns-retry-and-dead-lettering.md)). For a
subscription-consumed stream the dead-letter destination is the
`{stream}:dlq` stream the subscription publishes, and the Inline broker
redelivers a nacked message with no retry limit of its own.

The adapters differ when a stream is consumed straight off the broker, with no
subscription. The Inline broker moves a message to its own dead-letter queue
on exhausted retries and on in-flight timeout. Redis Streams can inspect and
replay `:dlq` streams that something else fills, and leaves a nacked message
pending.

Moving a message to the dead-letter queue does not lose it when that publish
fails. On both Redis Streams and Inline the source is acknowledged only after
the dead-letter publish succeeds. Until then the message is nacked after
`retry_delay_seconds`, keeps its retry count, and the move is retried at the
retry cadence. With `enable_dlq=False`, an exhausted message is acknowledged
and discarded.

---

## Cache

The cache holds projections keyed by id, with pattern queries. It is
best-effort and not durable, with a per-key TTL (300 seconds by default). It
promises no ordering, no transactions and no atomic multi-key operations. The
Memory cache lives in the process and is lost on exit. The Redis cache is as
durable as the Redis deployment is configured to be.

---

## How the guarantees are checked

Conformance and property tests cite a row on this page as their expected
behavior.

Four protocols have model-checked TLA+ specifications under
[`specs/`](https://github.com/proteanhq/protean/tree/main/specs): the `$all`
checkpoint advance, the outbox publish, the aggregate OCC commit, and failure
recovery. The TLC model checker explores every interleaving of out-of-order
commits, lock expiry, redelivery, crashes, concurrent writers and handler
failures, up to a bound, and checks the invariants that state these
guarantees. `specs/README.md` maps each invariant to its guarantee here. Each
spec has a revert test that puts the original bug back and confirms the model
catches it.

The specs check the design. They are re-run when a protocol changes, and are
not part of CI.

---

## Out of scope

- **Delivery of `published` events across bounded contexts**: Whether a
  `published=True` event carries a delivery guarantee to external subscribers
  is not settled yet
  ([ADR-0002](../adr/0002-event-publication-visibility.md), *Proposed*).
- **Nested Units of Work**: An inner Unit of Work has no commit of its own; see
  [Known exceptions](#persistence-exceptions) under Aggregate persistence.
- **Email adapters**: The shipped email adapters send and forget. They have no
  delivery guarantee, no retry and no outbox integration.

---

## Related reading

- [Applicability charter](applicability.md): Whether Protean fits your system at
  all, before you weigh this contract.
- [Versioning policy](versioning-policy.md): A weakened guarantee here is a
  breaking change; this is how such changes are handled.
- [Stable surface](stable-surface.md): What the compatibility contract covers,
  tier by tier.
