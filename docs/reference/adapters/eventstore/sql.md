# SQL event store

The `sql` event store keeps events and snapshots in tables on a SQLite file or
a PostgreSQL database. It talks to the database through SQLAlchemy and needs no
database extension.

Without a `database_uri`, the store shares the `default` database and its
engine, and its writes commit or roll back with the Unit of Work. With a
`database_uri`, the store opens its own engine and commits each write at once.
On PostgreSQL that URI can name the application's database or a different
one. On SQLite it must name a different file from the application's: SQLite
allows one writer per file, so an append on the store's own connection waits
for the Unit of Work's write lock and fails with `database is locked`.

[ADR-0048](../../../adr/0048-sql-event-store.md) records the design decisions.

## What the SQL event store guarantees

The SQL event store declares
`EventStoreCapabilities.PRODUCTION | EventStoreCapabilities.SCHEMA_MANAGEMENT`.
It writes and reads streams, categories and the whole store, checks expected
versions, makes category writes visible in global-position order, keeps
messages across restarts, and creates and drops its own tables. See
[What each event store guarantees](./index.md#what-each-event-store-guarantees)
for each flag.

It does not declare `CONSUMER_GROUPS`. A category read with
`consumer_group_member` or `consumer_group_size` raises `NotSupportedError`.

## Installation

Install the extra for your database. Both include SQLAlchemy:

```bash
pip install "protean[sqlite]"
# -- or --
pip install "protean[postgresql]"
```

Without SQLAlchemy, a domain with `provider = "sql"` raises
`ConfigurationError` when the domain builds its event store, and the message
names both extras.

## Configuration

On SQLite:

```toml
--8<-- "adapters/eventstore/sql/configuration.toml"
```

On PostgreSQL:

```toml
--8<-- "adapters/eventstore/sql/postgresql.toml"
```

`${SQL_EVENT_STORE_URL|...}` reads the URI from the `SQL_EVENT_STORE_URL`
environment variable, and uses the value after `|` when it is not set.

Sharing the `default` database:

```toml
--8<-- "adapters/eventstore/sql/shared.toml"
```

### Configuration options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"sql"` |
| `database_uri` | None | A `sqlite:///` file path or a `postgresql://` URL. Without it, the store shares the `default` database. |
| `schema` | `"public"` | The PostgreSQL schema that holds the tables, on a store with its own `database_uri`. The schema must exist. SQLite has no schemas, so setting it there raises `ConfigurationError`. A shared store uses the `default` database's schema, so setting it there raises `ConfigurationError`. |

On a store with its own `database_uri`, every other key goes to SQLAlchemy's
`create_engine`. On PostgreSQL the engine
starts from the defaults of the
[PostgreSQL database provider](../database/postgresql.md) (`pool_size` 5,
`max_overflow` 10, `pool_pre_ping` on, `pool_recycle` 1800 seconds), and the
config overrides them.

A `postgresql://` URL with no driver uses psycopg 3 when it is installed, and
psycopg2 otherwise. A URL that names a driver, such as
`postgresql+psycopg2://`, keeps it.

### Which databases it refuses

The store raises `ConfigurationError` when it is built with:

- a `database_uri` that is not a string, or that SQLAlchemy cannot parse
- a database other than SQLite or PostgreSQL
- an in-memory SQLite database, such as `sqlite://` or `sqlite:///:memory:`.
  Each connection to an in-memory database sees a different, empty database,
  so the store needs a file.
- `execution_options` that is not a table
- on PostgreSQL, a `schema` that is not a string, or is empty or only
  whitespace
- an isolation level other than the ones the store accepts, set with
  `isolation_level` or `execution_options.isolation_level`. PostgreSQL accepts
  `READ COMMITTED` and `READ UNCOMMITTED`, and SQLite accepts `SERIALIZABLE`
  and `READ UNCOMMITTED`. Two levels break the expected-version check:
    - `AUTOCOMMIT` on either database, because the version check and the
      insert would commit separately
    - `REPEATABLE READ` or `SERIALIZABLE` on PostgreSQL, because the
      transaction reads a snapshot taken before the category lock is granted

On PostgreSQL a store with its own `database_uri` sets `READ COMMITTED` on
every connection its engine opens. A default set on the server, the role or
through `connect_args` does not change the level the store's writes run at.
A shared store writes at the level of the `default` database's connections.
On PostgreSQL it opens one of those connections at start-up and reads its
level, so a level set on the server, the role or through `connect_args` is
checked too. A command that renders SQL without a database, such as
`protean db upgrade --sql`, skips this connection check.

A shared store raises `ConfigurationError` at start-up when its own config
sets `schema`, or when the `default` database is:

- not a `sqlite` or `postgresql` database provider, such as the `memory`
  provider or Elasticsearch
- an in-memory SQLite database
- set to an isolation level the store refuses, by the rules above
- on PostgreSQL, running its connections at `REPEATABLE READ` or
  `SERIALIZABLE`

## Sharing the default database

A store with no `database_uri` writes on the Unit of Work's connection to the
`default` database. One transaction holds the events of event-sourced
aggregates, the commands that `domain.process()` stores, process manager
transitions, and the rows of state-based aggregates and the outbox rows in
the `default` database. A raise before the commit leaves none of them in the
database. An aggregate on another database commits in that database's own
transaction, after the `default` transaction. A failure between the two
commits leaves the events stored and the other database's rows missing.

Inside a Unit of Work, the store holds each message until the commit, and
`write_message` returns `None` in place of the stream position. At the
commit, the Unit of Work hands the store its aggregate events, which the
store adds to the held messages. Before the outbox rows are saved, the store
checks each expected version and inserts every held message. A version
conflict raises `ExpectedVersionError` from the commit and rolls back the
whole transaction. A read inside the Unit of Work does not see a held message.
When a commit fails after the store inserted its messages, a second
`commit()` on the same Unit of Work raises `TransactionError`. Roll the Unit
of Work back and run it again.

The store joins only a Unit of Work started in its own domain. Inside a Unit
of Work of another domain, it writes each message at once and returns the
position.
`domain.process()` returns `None` for an asynchronous command it sends inside
a Unit of Work, and records the command's idempotency key after the commit.
Outside a Unit of Work, the store writes at once and returns the position.

Snapshots and reads inside a Unit of Work run on its connection, so a
snapshot write rolls back with it. Outside a Unit of Work they run on a
connection of their own from the `default` pool.

On a shared SQLite file the store turns on WAL mode, sets a 5 second busy
timeout and starts every transaction on the file with `BEGIN IMMEDIATE`,
including the application's own reads and writes. A transaction waits for the
file's write lock when it starts, so two processes on one file wait in turn
instead of failing with `database is locked`.

`store.close()` leaves the shared engine and its pool to the `default`
provider.

## Creating the tables

The store keeps events in `messages` and snapshots in `snapshots`.
[`protean db setup`](../../cli/data/database.md#protean-db-setup) creates the
tables that do not exist yet, and `protean db drop` drops them. In code,
`domain.setup_database()` and `domain.drop_database()` do the same.
`DomainFixture.setup()` from `protean.integrations.pytest` calls
`setup_database()`, and `DomainFixture.teardown()` calls `drop_database()`.

Create the tables once before the first write. A write to a database without
the tables fails.

The `messages` table holds the Message DB columns (`global_position`, `id`,
`stream_name`, `position`, `type`, `data`, `metadata`, `time`) and a
`category` column. `global_position` starts at 1. Times are stored in UTC and
read back as UTC.

## How writes stay consistent

A write runs one transaction: it takes the category lock, reads the stream's
last position, checks the expected version and inserts the message. A write
waits while another write to the same category holds the lock. On PostgreSQL,
writes to different categories do not wait for each other.

- **On PostgreSQL** the lock is `pg_advisory_xact_lock(key)`. The key is
  Message DB's `hash_64` of `"<schema>.messages:<category>"`: the first 16 hex
  digits of the MD5 digest of that text, read as a signed 64-bit integer. For
  category `user` in schema `public`, the key is `-3616439629249783035`. The
  key format stays fixed across Protean versions, so writers of two versions
  take the same lock during a rolling deploy.
- **On SQLite** each connection turns on WAL mode (write-ahead logging, which
  lets readers run while a write is in progress) and a 5 second busy timeout,
  and starts each write with `BEGIN IMMEDIATE`. That statement takes the
  database's write lock before the version check reads, so one write runs at
  a time across the whole file. On a file of its own, a read starts with a
  plain `BEGIN` and takes no write lock, so it runs while another connection
  writes.

The `messages` table also has a unique constraint on `(stream_name,
position)`. A write that breaks it, such as one from a writer that did not
take the lock, raises `ExpectedVersionError`.

## Snapshots

A stream whose name holds `:snapshot-`, such as `user:snapshot-1`, is a
snapshot stream. The store keeps one row for it in the `snapshots` table and
replaces that row on each write. The row's `position` counts the writes from
0, and its `metadata` is always empty. A read of the stream returns that one
row, with `global_position` 0. Category reads and whole-store reads leave
snapshots out, and a snapshot write takes no global position.

`protean eventstore verify` also reads the snapshot of every stream with a `-`
in its name, other than snapshot streams, so it checks the snapshots this store
keeps apart from its events.

## Limitations

- **No consumer groups.** Use Message DB when a category read must be split
  across the members of a consumer group.
- **One writer at a time on SQLite.** Every write takes the whole file's
  write lock. A writer that waits longer than the busy timeout fails. On a
  shared file every transaction takes the lock, reads included.
- **Late global positions on a shared PostgreSQL store.** A shared store
  takes each message's `global_position` when it inserts the held messages,
  and the row becomes visible when the Unit of Work's transaction commits,
  after the outbox rows are saved and the other databases commit. A Unit of
  Work on another category can commit a higher position in that time. A
  `$all` subscription waits `gap_timeout_seconds` (5 by default) at the
  missing position, then skips it for good. Keep the work after the insert
  shorter than that timeout, or raise `gap_timeout_seconds` under
  `[server.event_store_subscription]`. A category subscription is
  not affected, because the category lock orders the writes of one category.
- **No negative `limit`.** A read with a negative `limit` raises `ValueError`
  on both databases.

## Related pages

- [Event store overview](./index.md) for the operations every store offers
- [Message DB](./message-db.md), the other durable event store
- [`protean events`](../../cli/data/events.md) to read and inspect streams
