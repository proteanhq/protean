# Memory Provider

The Memory provider is an in-memory database adapter that stores data in Python
dictionaries. It is the default provider in Protean. It requires no external
dependencies.

## What is the Memory provider for?

The Memory provider is designed for:

- **Development environments** where simplicity and speed are key
- **Testing scenarios** where deterministic behavior is required
- **Prototyping** when you want to defer technology decisions
- **CI pipelines** that should run without external services

The Memory provider stores data using Python dictionaries protected by
threading locks:

- Records are kept in `defaultdict(dict)` keyed by entity class name
- Thread-safe access via `Lock` for concurrent operations
- All data is lost when the process terminates

The Memory provider is the default provider, so you need no configuration at
all. A fresh domain uses the Memory provider automatically.

## Configure the Memory provider

```toml
[databases.default]
provider = "memory"
```

### Which options does the Memory provider take?

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"memory"` for the Memory provider |

No other options are needed. There is no connection URI, no pool size, no
schema, just `provider = "memory"`.

## Which capabilities does the Memory provider support?

The Memory provider supports the following capabilities:

- :white_check_mark: **CRUD**: Create, Read, Update, Delete single records
- :white_check_mark: **FILTER**: Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS**: `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING**: Server-side ordering of results
- :white_check_mark: **SIMULATED_TRANSACTIONS**: Copy-on-write UoW semantics
- :white_check_mark: **OPTIMISTIC_LOCKING**: Version-based concurrency control
- :white_check_mark: **RAW_QUERIES**: JSON-string query criteria
- :x: **TRANSACTIONS**: No real database-level atomicity
- :x: **SCHEMA_MANAGEMENT**: No tables or indices to manage
- :x: **CONNECTION_POOLING**: No external connections
- :x: **NATIVE_JSON**: No native JSON column type
- :x: **NATIVE_ARRAY**: No native array column type

!!!note
    The Memory provider uses **simulated transactions**, not real ones. Within
    a Unit of Work, the provider tracks changes and applies them on commit. A
    rollback only discards uncommitted changes. It cannot undo side effects
    that already happened in the Python process.

## How does the Memory provider enforce indexes?

The memory provider accepts [`Index`](../../domain-elements/indexes.md)
declarations and validates them for shape at `Domain.init()`. Non-unique
indexes are **advisory**, because the in-memory store performs no index-backed
lookups. **Unique** indexes (`Index(..., unique=True)`) are **enforced**: a
duplicate insert or update that violates a single-column or composite unique
index raises `ValidationError`. Protean raises the same error for a field-level
`unique=True`. A SQL backend rejects the duplicate at the database instead.
NULLs are treated as distinct (PostgreSQL/SQLite semantics). The memory
provider accepts the same index declarations as a SQL backend. You can declare
the indexes your aggregates need, develop against the memory provider, and
switch to a SQL backend without changing the domain.

## Run raw queries

The Memory provider supports raw queries through JSON-string criteria that are
evaluated against in-memory records:

```python
--8<-- "adapters/database/memory/001.py:full"
```

`results` holds one record, Ada's. Tim is too young and Lin is inactive.

The query string is parsed as JSON and interpreted as filter criteria using the
same lookup syntax as the QuerySet API.

## How do datetime lookups compare values?

`exact`, `in`, `lt`, `lte`, `gt`, `gte`, `any` and `overlap` compare two
datetimes as UTC instants, so `12:00+00:00` equals `14:00+02:00`. A naive
datetime on either side is read as UTC. `contains`, `startswith` and
`endswith` compare the string form, and so does a datetime filtered with a
string.

## What are the Memory provider's limits?

- **Data does not persist**: Data is lost on process restart. The Memory
  provider is purely ephemeral.
- **Transactions are simulated**: Simulated transactions commit atomically and
  roll back uncommitted changes, but only within one Python process. Nothing is
  durable.
- **The provider does not distribute data**: The provider holds all data in a
  single Python process. Cannot scale across multiple processes or machines.
- **The provider manages no schema**: There are no tables or indices to create
  or drop. `_create_database_artifacts()` and `_drop_database_artifacts()` are
  no-ops.
- **JSON and array fields are not native**: Complex fields are stored as
  serialized Python objects instead of native database types.

## Move to a production provider

The Memory provider is designed to be easily replaced with production-ready
providers:

```toml
# Development configuration (default)
[databases.default]
provider = "memory"

# Production configuration (same domain code works!)
[databases.default]
provider = "postgresql"
database_uri = "postgresql://user:pass@db.example.com:5432/myapp"
```

All providers implement the same `BaseProvider` interface, so your domain code
stays the same when you switch providers. To switch, update the configuration,
and Protean uses the new provider.

## Read related pages

- Learn about [SQLite](./sqlite.md) for local development with real SQL
  semantics
- Learn about [PostgreSQL](./postgresql.md) for production environments
- Understand [database capabilities](./index.md#how-providers-declare-capabilities) in
  detail
- See the [Dual-Mode Testing](../../../patterns/dual-mode-testing.md) pattern
  for running the same tests against memory and real databases
