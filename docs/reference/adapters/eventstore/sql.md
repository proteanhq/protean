# SQL event store

The `sql` event store keeps events and snapshots in tables on a SQLite file or
a PostgreSQL database. It talks to the database through SQLAlchemy and needs no
database extension. It uses its own `database_uri`, which can name the same
database as your application or a different one.

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

### Configuration options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"sql"` |
| `database_uri` | Required | A `sqlite:///` file path or a `postgresql://` URL |
| `schema` | `"public"` | The PostgreSQL schema that holds the tables. The schema must exist. SQLite has no schemas, so setting it there raises `ConfigurationError`. |

Every other key goes to SQLAlchemy's `create_engine`. On PostgreSQL the engine
starts from the defaults of the
[PostgreSQL database provider](../database/postgresql.md) (`pool_size` 5,
`max_overflow` 10, `pool_pre_ping` on, `pool_recycle` 1800 seconds), and the
config overrides them.

A `postgresql://` URL with no driver uses psycopg 3 when it is installed, and
psycopg2 otherwise. A URL that names a driver, such as
`postgresql+psycopg2://`, keeps it.

### Which databases it refuses

The store raises `ConfigurationError` when it is built with:

- no `database_uri`, or one SQLAlchemy cannot parse
- a database other than SQLite or PostgreSQL
- an in-memory SQLite database, such as `sqlite://` or `sqlite:///:memory:`.
  Each connection to an in-memory database sees a different, empty database,
  so the store needs a file.
- `execution_options` that is not a table
- on PostgreSQL, a `schema` that is not a non-empty string
- an isolation level other than the ones the store accepts, set with
  `isolation_level` or `execution_options.isolation_level`. PostgreSQL accepts
  `READ COMMITTED` and `READ UNCOMMITTED`, and SQLite accepts `SERIALIZABLE`
  and `READ UNCOMMITTED`. Two levels break the expected-version check:
    - `AUTOCOMMIT` on either database, because the version check and the
      insert would commit separately
    - `REPEATABLE READ` or `SERIALIZABLE` on PostgreSQL, because the
      transaction reads a snapshot taken before the category lock is granted

On PostgreSQL the store's engine sets `READ COMMITTED` on every connection it
opens. A default set on the server, the role or through `connect_args` does
not change the level the store's writes run at.

## Creating the tables

The store keeps events in `messages` and snapshots in `snapshots`.
[`protean db setup`](../../cli/data/database.md#protean-db-setup) creates the
tables that do not exist yet, and `protean db drop` drops them. In code,
`domain.setup_database()` and `domain.drop_database()` do the same. The
Protean pytest plugin calls `setup_database()` before a test session.

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
  a time across the whole file. A read starts with a plain `BEGIN` and takes
  no write lock, so it runs while another connection writes.

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

`protean eventstore verify` reads the snapshot of each aggregate stream
separately, so it checks the snapshots this store keeps apart from its events.

## Limitations

- **No consumer groups.** Use Message DB when a category read must be split
  across the members of a consumer group.
- **One writer at a time on SQLite.** Every write takes the whole file's
  write lock. A writer that waits longer than the busy timeout fails.
- **No negative `limit`.** A read with a negative `limit` raises `ValueError`
  on both databases.

## Related pages

- [Event store overview](./index.md) for the operations every store offers
- [Message DB](./message-db.md), the other durable event store
- [`protean events`](../../cli/data/events.md) to read and inspect streams
