# PostgreSQL

The PostgreSQL provider uses [SQLAlchemy](https://www.sqlalchemy.org/) under
the covers as the ORM to communicate with the database. It is the recommended
provider for production deployments.

## Overview

PostgreSQL is a relational provider that supports the full
range of database capabilities, including native JSON and array columns. It
provides real ACID transactions, connection pooling, and schema management.

## Installation

```bash
pip install "protean[postgresql]"
```

This installs [psycopg 3](https://www.psycopg.org/psycopg3/) with its binary
package (`psycopg[binary]`), which needs no build step and no system
`libpq`. psycopg 3 is the default driver.

To build against your system's `libpq` instead, install `psycopg` without the
binary package. See the [psycopg 3 installation
guide](https://www.psycopg.org/psycopg3/docs/basic/install.html) for the
prerequisites.

### Using psycopg2

The provider also supports psycopg2. Install it with its own extra:

```bash
pip install "protean[postgresql-psycopg2]"
```

This installs `psycopg2-binary`. Install `psycopg2` in its place to build from
source. Both provide the same `psycopg2` module, so install only one. See the
[psycopg2 installation guide](https://www.psycopg.org/docs/install.html).

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
postgresql[+driver]://[username]:[password]@[host]:[port]/[database]

# Examples:
postgresql://postgres:postgres@localhost:5432/postgres
postgresql://user:pass@db.example.com:5432/myapp
postgresql://user:pass@db.example.com/myapp?sslmode=require
postgresql+psycopg2://user:pass@db.example.com:5432/myapp
```

### Choosing the driver

The driver comes from the URL:

| `database_uri` | Driver |
|----------------|--------|
| `postgresql+psycopg://...` | psycopg 3 |
| `postgresql+psycopg2://...` | psycopg2 |
| `postgresql://...` | psycopg 3 if it is installed, otherwise psycopg2 |

Protean resolves the plain `postgresql://` form itself, so it means the same
driver on SQLAlchemy 2.0 and 2.1. The provider logs the driver it chose as
`repository.postgresql.driver_selected` at `INFO`.

If the driver a URL needs cannot be imported, `domain.init()` raises a
`ConfigurationError` that names the extra to install. A URL that names a
psycopg2 driver does not fall back to psycopg 3. Write the driver into the URL
when you want to control which one runs.

## Capabilities

The PostgreSQL provider supports the following capabilities:

- :white_check_mark: **CRUD**: Create, Read, Update, Delete single records
- :white_check_mark: **FILTER**: Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS**: `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING**: Server-side `ORDER BY` support
- :white_check_mark: **TRANSACTIONS**: Real commit/rollback ACID atomicity
- :white_check_mark: **OPTIMISTIC_LOCKING**: Version-based concurrency control
- :white_check_mark: **RAW_QUERIES**: Execute raw SQL queries
- :white_check_mark: **SCHEMA_MANAGEMENT**: Create/drop tables and indices
- :white_check_mark: **CONNECTION_POOLING**: SQLAlchemy connection pool management
- :white_check_mark: **NATIVE_JSON**: PostgreSQL `JSONB` column type
- :white_check_mark: **NATIVE_ARRAY**: PostgreSQL `ARRAY` column type

PostgreSQL is the only built-in provider that supports **all 12 capability
flags** (excluding `SIMULATED_TRANSACTIONS`, which is specific to the Memory
provider).

## Indexes

PostgreSQL honors the full [`Index`](../../domain-elements/indexes.md) surface.
Declarations on an aggregate or entity are emitted as `CREATE INDEX` statements
during `protean db setup`:

- Composite, descending (`desc=`), and unique (`unique=`) indexes.
- Partial indexes (`where=Q(...)`) via `CREATE INDEX … WHERE …`.
- Covering columns (`include=`) via `INCLUDE (...)`.
- Storage-specific indexes (GIN, GiST, BRIN, expression) via
  `Index.from_sql("postgresql", ddl)`.

## SQLAlchemy Model

You can supply a custom SQLAlchemy Model in place of the one that Protean
generates internally, allowing you full customization.

```python hl_lines="10-15 24-27"
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

## Slow Query Detection

Protean installs SQLAlchemy ``before_cursor_execute`` /
``after_cursor_execute`` listeners on the engine at provider construction
time and emits two structured log events per query:

- ``protean.adapters.repository.sqlalchemy.query`` at **DEBUG** for every
  query (opt-in via normal level configuration).
- ``protean.adapters.repository.sqlalchemy.slow_query`` at **WARNING** when
  a query exceeds the configured threshold.

Both events carry ``statement``, ``parameters``, ``duration_ms``, and
``threshold_ms``. The slow-query logger is separate so operators can route
its alerts independently (e.g. to PagerDuty) while leaving the DEBUG
tracing logger silent in production.

Tune the behavior via the ``[logging]`` section of ``domain.toml``:

```toml
[logging]
slow_query_threshold_ms = 100    # WARN when a query exceeds this (ms)
slow_query_truncate_chars = 500  # max statement length in log events
```

Set ``slow_query_threshold_ms = 0`` to WARN on every query (useful during
performance investigations). Correlation context (``correlation_id``,
``causation_id``) flows onto every record automatically via the
``ProteanCorrelationFilter`` on the root logger's handlers.

## Limitations

- **Requires Running Server**: PostgreSQL must be installed and running as a
  separate service. Use `make up` to start Protean's Docker-based development
  services.
- **Connection Overhead**: Each connection consumes server resources. Tune
  `pool_size` and `max_overflow` for your workload.

## Related pages

- Learn about [database capabilities](./index.md#database-capabilities) in
  detail
- Explore [Elasticsearch](./elasticsearch.md) for search-oriented storage
- See [Building Custom Database Adapters](./custom-databases.md) to support
  other databases
- Learn about
  [setting up databases for tests](../../../patterns/setting-up-and-tearing-down-database-for-tests.md)
