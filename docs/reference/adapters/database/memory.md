# Memory Provider

The Memory provider is an in-memory database adapter that stores data in Python
dictionaries. It is the default provider in Protean and requires no external
dependencies.

## Overview

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

Because it is the default provider, no configuration is needed at all -- a
fresh domain uses the Memory provider automatically.

## Configuration

```toml
[databases.default]
provider = "memory"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"memory"` for the Memory provider |

No other options are needed. There is no connection URI, no pool size, no
schema -- just `provider = "memory"`.

## Capabilities

The Memory provider supports the following capabilities:

- :white_check_mark: **CRUD** -- Create, Read, Update, Delete single records
- :white_check_mark: **FILTER** -- Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS** -- `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING** -- Server-side ordering of results
- :white_check_mark: **SIMULATED_TRANSACTIONS** -- Copy-on-write UoW semantics
- :white_check_mark: **OPTIMISTIC_LOCKING** -- Version-based concurrency control
- :white_check_mark: **RAW_QUERIES** -- JSON-string query criteria
- :x: **TRANSACTIONS** -- No real database-level atomicity
- :x: **SCHEMA_MANAGEMENT** -- No tables or indices to manage
- :x: **CONNECTION_POOLING** -- No external connections
- :x: **NATIVE_JSON** -- No native JSON column type
- :x: **NATIVE_ARRAY** -- No native array column type

!!!note
    The Memory provider uses **simulated transactions**, not real ones. Within
    a Unit of Work, changes are tracked and applied on commit, but a rollback
    only discards uncommitted changes -- it cannot undo side effects that
    already happened in the Python process.

## Raw Queries

The Memory provider supports raw queries through JSON-string criteria that are
evaluated against in-memory records:

```python
results = domain.providers["default"].raw(
    '{"age__gt": 21, "status": "active"}'
)
```

The query string is parsed as JSON and interpreted as filter criteria using the
same lookup syntax as the QuerySet API.

## Limitations

- **No Persistence** -- Data is lost on process restart. The Memory provider
  is purely ephemeral.
- **No Real Transactions** -- Simulated transactions track changes but cannot
  provide true rollback or ACID guarantees.
- **No Distribution** -- All data lives in a single Python process. Cannot
  scale across multiple processes or machines.
- **No Schema Management** -- There are no tables or indices to create or
  drop. `_create_database_artifacts()` and `_drop_database_artifacts()` are
  no-ops.
- **No Native JSON/Array** -- Complex fields are stored as serialized Python
  objects, not as native database types.

## Migration Path

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

Your domain code remains unchanged when switching providers, because all
providers implement the same `BaseProvider` interface. Just update the
configuration and Protean handles the rest.

## Next Steps

- Learn about [SQLite](./sqlite.md) for local development with real SQL
  semantics
- Learn about [PostgreSQL](./postgresql.md) for production environments
- Understand [database capabilities](./index.md#database-capabilities) in
  detail
- See the [Dual-Mode Testing](../../../patterns/dual-mode-testing.md) pattern
  for running the same tests against memory and real databases
