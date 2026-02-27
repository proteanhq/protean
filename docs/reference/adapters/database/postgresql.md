# PostgreSQL

The PostgreSQL provider uses [SQLAlchemy](https://www.sqlalchemy.org/) under
the covers as the ORM to communicate with the database. It is the recommended
provider for production deployments.

## Overview

PostgreSQL is a production-grade relational provider that supports the full
range of database capabilities, including native JSON and array columns. It
provides real ACID transactions, connection pooling, and schema management.

## Installation

```bash
pip install "protean[postgresql]"
```

This installs `psycopg2-binary`, a pre-compiled binary that works out of the box
with no system dependencies.

For production deployments, you may prefer `psycopg2` (compiled from source
against your system's `libpq`). To use it, install it explicitly in place of
`psycopg2-binary`:

```bash
pip install psycopg2
```

Both packages provide the same `psycopg2` Python module — only one should be
installed at a time. See the
[psycopg2 installation guide](https://www.psycopg.org/docs/install.html) for
system prerequisites when building from source.

## Configuration

```toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/postgres"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"postgresql"` for PostgreSQL |
| `database_uri` | Required | Connection string (see format below) |
| `schema` | `None` | Database schema to use (e.g. `"myapp"`) |
| `pool_size` | `5` | Number of connections in the SQLAlchemy connection pool |
| `max_overflow` | `10` | Additional connections allowed beyond `pool_size` |

### Connection String Format

```
postgresql://[username]:[password]@[host]:[port]/[database]

# Examples:
postgresql://postgres:postgres@localhost:5432/postgres
postgresql://user:pass@db.example.com:5432/myapp
postgresql://user:pass@db.example.com/myapp?sslmode=require
```

## Capabilities

The PostgreSQL provider supports the following capabilities:

- :white_check_mark: **CRUD** -- Create, Read, Update, Delete single records
- :white_check_mark: **FILTER** -- Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS** -- `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING** -- Server-side `ORDER BY` support
- :white_check_mark: **TRANSACTIONS** -- Real commit/rollback ACID atomicity
- :white_check_mark: **OPTIMISTIC_LOCKING** -- Version-based concurrency control
- :white_check_mark: **RAW_QUERIES** -- Execute raw SQL queries
- :white_check_mark: **SCHEMA_MANAGEMENT** -- Create/drop tables and indices
- :white_check_mark: **CONNECTION_POOLING** -- SQLAlchemy connection pool management
- :white_check_mark: **NATIVE_JSON** -- PostgreSQL `JSONB` column type
- :white_check_mark: **NATIVE_ARRAY** -- PostgreSQL `ARRAY` column type

PostgreSQL is the only built-in provider that supports **all 12 capability
flags** (excluding `SIMULATED_TRANSACTIONS`, which is specific to the Memory
provider).

## SQLAlchemy Model

You can supply a custom SQLAlchemy Model in place of the one that Protean
generates internally, allowing you full customization.

```python hl_lines="8-11 20-23"
--8<-- "adapters/database/postgresql/001.py:full"
```

!!!note
    The column names specified in the model should exactly match the attribute
    names of the Aggregate or Entity it represents.

## Raw Queries

Use the `raw()` method to execute SQL directly:

```python
results = domain.providers["default"].raw(
    "SELECT * FROM users WHERE age > :age",
    {"age": 21}
)
```

Raw queries execute immediately in their own transaction context. Results are
returned as-is from the database without entity conversion.

## Limitations

- **Requires Running Server** -- PostgreSQL must be installed and running as a
  separate service. Use `make up` to start Protean's Docker-based development
  services.
- **Connection Overhead** -- Each connection consumes server resources. Tune
  `pool_size` and `max_overflow` for your workload.

## Next Steps

- Learn about [database capabilities](./index.md#database-capabilities) in
  detail
- Explore [Elasticsearch](./elasticsearch.md) for search-oriented storage
- See [Building Custom Database Adapters](./custom-databases.md) to support
  other databases
- Learn about
  [setting up databases for tests](../../../patterns/setting-up-and-tearing-down-database-for-tests.md)
