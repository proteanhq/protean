# ADR-0048: Protean stores events in SQLite and PostgreSQL through SQLAlchemy

**Status:** Proposed

**Date:** November 2026

## Context

Protean's durable event store, Message DB, requires a PostgreSQL server with
Message DB's schema and stored functions installed. Domains on SQLite, or on
PostgreSQL without Message DB, had no durable event store.

The event-store Port
([#2050](https://github.com/proteanhq/protean/issues/2050)) defines the
methods, capability flags and conformance suite
([#2063](https://github.com/proteanhq/protean/issues/2063)) every event store
implements. The SQL event store implements the Port through SQLAlchemy and
matches the Message DB store's behaviour except where stated below.

Relevant Protean behaviour:

- The Unit of Work flushes sessions, appends aggregate events, saves outbox
  rows, then commits sessions. It is one transaction at `READ COMMITTED`
  ([ADR-0027](0027-unit-of-work-is-a-real-transaction.md)).
- Message DB commits each append on its own connection, before the sessions
  commit. That append is the durable anchor: once it succeeds, the command
  counts as done ([ADR-0015](0015-event-store-append-as-durable-anchor.md)).
- Message DB holds a per-category lock until commit, so each category commits
  in position order. A `$all` subscription reads every category by global
  position. A position can be missing because its transaction has not committed
  yet or has rolled back, so the subscription waits `gap_timeout_seconds`
  (default 5) at a missing position before moving on
  ([ADR-0025](0025-all-subscription-gap-safety.md)).
- `ExpectedVersionError` triggers `version_retry`, which reruns the handler
  from the start.
- Commands sent through `domain.process()` and process manager transition
  events are appended as soon as they are produced. Aggregate events wait for
  the commit. Inside a handler, a synchronously processed command's handler
  joins the outer Unit of Work.
- SQLite permits one writer per file. An event store writing to the aggregates'
  file on a separate connection waits for the Unit of Work's write lock and
  fails at the busy timeout.
- With `tick_interval = 0` and `max_tick_interval = 0`, an idle event-store
  subscription polls continuously
  ([#959](https://github.com/proteanhq/protean/issues/959)).

Event stores in other ecosystems (Rails Event Store, Sequent, Marten,
Commanded, Emmett, Axon, Akka Persistence) show three patterns. The
longest-running ones write events in the application's own transaction. Every
long-lived store changed its schema at least once. Stores with their own
migration-tracking table conflicted with the application's migrations.

## Decision

### 1. Provider `sql` serves SQLite and PostgreSQL

```toml
[event_store]
provider = "sql"                 # shares the "default" database provider
# database_uri = "postgresql://user:pass@host/events"   # separate database
```

- Without `database_uri`, the store shares the `default` provider. With it, the
  store uses a separate database. A domain whose SQL database provider is not
  `default` makes it `default` or sets `database_uri`.
- The database type comes from the `default` provider or the URL scheme. Any
  type other than SQLite or PostgreSQL fails at start-up with an error that
  lists the supported types.
- A domain can still choose `memory` or `message_db` as its event store,
  whatever its database provider.
- `protean new` offers `sql` alongside `memory` and `message-db`.

One name covers both databases because one code path writes to both (decision
3).

### 2. A shared store appends in the Unit of Work's transaction

- Sharing `default`: the store appends on the provider's session, obtained from
  the active Unit of Work as the memory store does, so `write_message` takes no
  session argument. Events, aggregate rows and outbox rows commit or roll back
  together.
- Inside a Unit of Work, the store collects every message appended during the
  handler, including commands and process manager transition events, and writes
  them at commit with the aggregate events. A command sent by a handler that
  fails rolls back with it. A handler that sends a command and reaches no
  repository opens its transaction at commit, after its body returns
  ([ADR-0031](0031-handlers-persist-or-call-out.md), as amended).
- With no active Unit of Work, as for an API endpoint's `domain.process()` call
  or a subscription's position write, the store commits the append in its own
  transaction.
- With `database_uri`: the store commits each append on its own connection, as
  Message DB does. ADR-0015 applies unchanged.

A SQLite deployment with aggregates and events in one file works only with the
shared transaction, because SQLite permits one writer per file.

### 3. Write logic is Python on SQLAlchemy Core

Per message, in one transaction: take the category lock, read the stream's last
position, check the expected version, assign the global position, insert. Both
databases run this code. Only the lock statement differs, and the conformance
suite runs on each database.

One code path lets one suite test the write logic on both databases. Any
optimised replacement, such as a single-statement PostgreSQL write using CTEs,
must pass the same suite.

### 4. Locking and ordering follow Message DB

- PostgreSQL: a transaction-scoped advisory lock per category, held until
  commit and keyed by Message DB's `hash_64` of `<schema>.<table_name>` plus
  the category. Domains in separate schemas of one database therefore never
  contend for a lock. A sequence assigns the global position.
- SQLite: the database write lock. `AUTOINCREMENT` assigns the global position
  and never reuses one after a delete.
- Appends to different categories do not block each other.
- `$all` subscriptions read by global position with Protean's ADR-0025 gap
  wait, as on the Message DB store. Every append in a Unit of Work happens at
  commit, immediately before the outbox save, so the time between assigning a
  position and committing it is short. A subscription skips an event only when
  that commit exceeds `gap_timeout_seconds`, which a domain with slow commits
  raises under `[server.event_store_subscription]`.

At commit, the store takes the category locks for all collected messages in
sorted key order, then writes the messages in the order they were produced. A
fixed lock order means two appending transactions cannot deadlock on each
other's category locks. For any other lock cycle, PostgreSQL aborts one
transaction with a deadlock error, and the handler fails. Version retry covers
only `ExpectedVersionError`, so the handler runs again only when transient
retry is configured.

Lock keys and position rules are a stable contract. Old and new code append
side by side during a rolling deploy, so changing either requires stopping
every writer first.

### 5. Expected-version semantics follow Message DB

- The check runs under the category lock. `None` skips it, `-1` requires a new
  stream, and any other value must equal the stream's last position.
- A stale write raises `ExpectedVersionError` and writes nothing.
- `UNIQUE (stream_name, position)` rejects any duplicate the check misses. Each
  driver's unique-violation error maps to `ExpectedVersionError`.
- Conformance tests cover three defects found in other stores: an insert that
  swallows the conflict, a first write that skips the check, and a check that
  runs after the global position is assigned.

The store does not detect an append that already succeeded. `version_retry`
reruns the handler from the start, because the state the handler read may have
changed. The rerun creates new event ids, so a check by event id would never
match, and retrying only the append would store a decision based on stale
state.

### 6. Unsafe configurations fail at start-up

- An engine in `AUTOCOMMIT` mode. Each statement would commit separately and
  release the category lock before the insert.
- A shared `default` provider with an isolation level stricter than `READ
  COMMITTED`. Under `REPEATABLE READ` or `SERIALIZABLE`, the transaction reads
  a snapshot taken before the lock, so the version check sees stale data.

### 7. The events table has no triggers, and `protean eventstore prune` deletes events

The events table has no triggers, as in Message DB. Database permissions govern
who may update or delete rows.

`protean eventstore prune` deletes events under rules a hand-written `DELETE`
cannot apply:

- Within a stream, it deletes only events before the latest snapshot, so an
  event-sourced aggregate still loads. It deletes a whole stream only when the
  operator asks for that stream.
- It deletes only events every subscription has read, according to the
  subscriptions' stored positions. A deleted row ahead of a `$all` subscription
  would leave a gap, and the subscription would wait `gap_timeout_seconds`
  there.

### 8. Snapshots are stored in a separate table

The store keeps snapshots in their own table, one row per aggregate, and routes
`:snapshot-` streams to it in `write_message` and stream reads. The Port is
unchanged.

- A snapshot takes no global position, so it creates no `$all` gap or gap wait
  ([#2105](https://github.com/proteanhq/protean/issues/2105) describes that
  wait on Message DB).
- Removing old snapshots does not touch the events table.
- A snapshot format change requires clearing one table.

### 9. Protean does not alter a production schema

- The store declares `SCHEMA_MANAGEMENT`. `protean db setup` creates its tables
  for development and tests.
- For production, Protean prints the DDL for a person to review and run.
- For later schema changes, `protean upgrade-check` reads the live schema and
  prints the SQL, as for the outbox.
- The store registers its tables in the provider's SQLAlchemy `MetaData`,
  exposed through the provider's public `metadata` property, so migration tools
  such as Alembic see them with the application's tables.
- Protean keeps no migration-tracking table. Schema changes go through the
  application's own migration tool.

### 10. SQLite concurrency settings apply only to files the store writes to

On the shared `default` SQLite provider, or on the store's own engine:

- WAL mode, so readers proceed while one writer writes.
- A 5-second busy timeout, the default of Python's `sqlite3` module.
- `BEGIN IMMEDIATE`. Without it, two transactions that both read and then write
  fail at once with `database is locked`, because SQLite cannot upgrade both to
  the write lock ([#2108](https://github.com/proteanhq/protean/issues/2108)).

`BEGIN IMMEDIATE` makes every transaction on the file take the write lock at
the start, read-only ones included, so other SQLite databases keep their
settings unchanged. A test runs two processes against one file. Writers on more
than one machine require PostgreSQL.

### 11. Idle subscriptions back off exponentially

On every event store, an event-store subscription doubles its wait after each
empty read, up to `max_tick_interval` under
`[server.event_store_subscription]`, and resets on a non-empty read. The name
matches the outbox processor's setting. With the cap at 1 second by default, an
idle domain no longer polls its event store continuously. Subscriptions find
new messages by polling, as on Message DB.

### 12. The SQL event store does not support consumer groups

The store accepts `consumer_group_member` and `consumer_group_size`, does not
declare `CONSUMER_GROUPS`, and raises `NotSupportedError` when either is set.
Message DB's consumer groups have a fixed size that cannot change with load,
which is why Protean scales event handling through Redis stream subscriptions.
Fixed-size groups on the SQL event store would carry the same limit.

### 13. The SQL event store adds nothing to the Port

DDL printing and pruning stay in the SQL event store's adapter. A Port member
would require every event store to implement them.

## Consequences

**Positive:**

- SQLite and PostgreSQL domains get a durable event store in their existing
  database, with no extra server and, in the common case, one line of
  configuration.
- When sharing `default`, events, aggregate rows and outbox rows commit in one
  transaction. The two-commit window that ADR-0015 covers does not arise, and a
  command cannot apply twice after a failed relational commit
  ([#2107](https://github.com/proteanhq/protean/issues/2107)).
- Handlers move between the SQL and Message DB stores unchanged.
- Snapshots create no `$all` gaps.
- Category locks are held only during the commit and taken in one order, so
  appends do not deadlock on each other.
- A command sent by a handler that fails is not stored.
- One conformance suite covers both databases.

**Negative:**

- When sharing `default`, the category lock is held from the start of the
  commit through the outbox save, so appends to one category wait for each
  other that long.
- A `$all` subscription skips an event whose commit exceeds
  `gap_timeout_seconds`, as on Message DB.
- Each message takes three statements, and so three round trips.
- The team that runs the database applies production DDL and upgrade SQL by
  hand.
- Lock-key or position-rule changes require stopping every writer.
- The database does not prevent a user with write access from changing or
  deleting events.
- On SQLite, all writers run on one machine, and read-only transactions on a
  shared file take the write lock.
- An idle subscription reads a new event up to `max_tick_interval` late.
- A command sent from inside a handler reaches the engine when that handler
  commits.
- Each event-store subscription runs in one worker. Scaling out requires Redis
  stream subscriptions.
- ADR-0015's durable anchor does not apply when sharing `default`, because the
  append is part of the relational commit.

## Alternatives Considered

- **Write through a PL/pgSQL function, as Message DB does.** One round trip per
  message. Rejected: separate install and upgrade path on PostgreSQL, and a
  second implementation for SQLite.
- **Append commands and transition events when produced, as the Message DB
  store does.** Rejected: in the shared case each one holds its category lock
  and an open `$all` gap for the rest of the handler.
- **Always append on a separate connection.** Rejected: fails on a shared
  SQLite file and keeps the two-commit window everywhere.
- **Take a store-wide lock, so global positions commit in order.** No `$all`
  gaps from slow commits. Rejected: every append waits for the previous one, a
  cost neither Message DB nor Axon pays.
- **Track gaps in the subscription position and reread them later, as Axon's
  gap-aware tracking token does.** A late commit still reaches the subscriber.
  Rejected: it changes `$all` subscriptions on every store, and with all
  appends at commit the ADR-0025 gap wait covers the short gap.
- **Track one position per category in `$all` subscriptions and drop the gap
  wait.** Rejected: loses cross-category order and needs new subscription logic
  for a case the gap wait covers.
- **Hide rows of in-progress transactions from readers, as Watermill and Emmett
  do.** Rejected: readers stall behind any long transaction, and stream order
  breaks because the Unit of Work obtains its transaction id at flush, before
  it waits on the category lock.
- **Assign the global position as the maximum plus one.** No gap after a
  rollback. Rejected: safe only under a store-wide lock.
- **Prune with a hand-written `DELETE`.** Rejected: the operator would need to
  know which events aggregates and subscriptions still need.
- **Reject `UPDATE` and `DELETE` with triggers.** Rejected: Message DB has
  none, and pruning would need a bypass.
- **Wake subscribers with PostgreSQL `NOTIFY` on commit.** Rejected: PostgreSQL
  serialises the commits of transactions that issued `NOTIFY`, and polling with
  backoff serves Message DB.
- **Store snapshots in the events table, as Message DB does.** Rejected for the
  reasons in decision 8.
- **Add snapshot methods to the Port.** Rejected: every event store would
  implement them.
- **Ship versioned migrations with a Protean tracking table.** Rejected:
  conflicted with application migrations in other stores.
- **Apply the SQLite concurrency settings to every SQLite database.** Rejected:
  imposes the `BEGIN IMMEDIATE` cost on domains without the store.
- **Support consumer groups on both databases.** Rejected for the reason in
  decision 12.
- **Give each database its own provider name, or name the provider
  `sqlalchemy`.** Rejected: one code path serves both, Protean does not support
  every SQLAlchemy dialect, and no Protean config value is a library name.
- **Add a `database` key that names a provider other than `default`.**
  Rejected: readers take it for a database on the server, it reads as a second
  form of `database_uri`, and no domain has needed it.

## Dependencies

Decision 9 depends on the database provider's public `metadata` property.
