# SQL event store

The `sql` event store keeps events in two tables on a SQLite file or a
PostgreSQL database. It talks to the database through SQLAlchemy and needs no
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

Every other key goes to SQLAlchemy's `create_engine`, as on the
[SQLAlchemy database providers](../database/postgresql.md). On SQLite the
store drops `pool_size`, `max_overflow` and `pool_recycle`, because its engine
uses no pool that reads them.

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
- an isolation level that breaks the expected-version check, set with
  `isolation_level` or `execution_options.isolation_level`:
    - `AUTOCOMMIT` on either database, because the version check and the
      insert would commit separately
    - `REPEATABLE READ` or `SERIALIZABLE` on PostgreSQL, because the
      transaction reads a snapshot taken before the category lock is granted

## Creating the tables

The store keeps events in `messages` and snapshots in `snapshots`.
`create_schema()` creates the tables that do not exist yet, and
`drop_schema()` drops them:

```python
domain.init()
with domain.domain_context():
    domain.event_store._adapter.create_schema()
```

Call `create_schema()` once before the first write. A write to a database
without the tables fails.

The `messages` table holds the Message DB columns (`global_position`, `id`,
`stream_name`, `position`, `type`, `data`, `metadata`, `time`) and a
`category` column. `global_position` starts at 1. Times are stored in UTC and
read back as UTC.

## How writes stay consistent

A write runs one transaction: it takes the category lock, reads the stream's
last position, checks the expected version and inserts the message. Writers
to one category take turns, and writers to different categories run side by
side on PostgreSQL.

- **On PostgreSQL** the lock is `pg_advisory_xact_lock(key)`. The key is
  Message DB's `hash_64` of `"<schema>.messages:<category>"`: the first 16 hex
  digits of the MD5 digest of that text, read as a signed 64-bit integer. For
  category `user` in schema `public`, the key is `-3616439629249783035`. The
  key format stays fixed across Protean versions, so writers of two versions
  take the same lock during a rolling deploy.
- **On SQLite** each connection turns on WAL mode (write-ahead logging, which
  lets readers run while a write is in progress) and a 5 second busy timeout,
  and starts each transaction with `BEGIN IMMEDIATE`. That statement takes the
  database's write lock before the version check reads, so one write runs at
  a time across the whole file.

A unique constraint on `(stream_name, position)` backs the lock. A write that
breaks it raises `ExpectedVersionError`.

## Snapshots

A stream whose name holds `:snapshot-`, such as `user:snapshot-1`, is a
snapshot stream. The store keeps one row for it in the `snapshots` table and
replaces that row on each write. A read of the stream returns that one row,
with `global_position` 0. Category reads and whole-store reads leave snapshots
out, and a snapshot write takes no global position.

## Limitations

- **No consumer groups.** Use Message DB when a category read must be split
  across the members of a consumer group.
- **One writer at a time on SQLite.** Every write takes the whole file's
  write lock. A writer that waits longer than the busy timeout fails.

## Related pages

- [Event store overview](./index.md) for the operations every store offers
- [Message DB](./message-db.md), the other durable event store
- [`protean events`](../../cli/data/events.md) to read and inspect streams
