# Database Providers

Database providers abstract the underlying persistence technology, allowing
Protean to support various databases without changing domain or application
logic. Each provider implements the `BaseProvider` interface. Each provider
also declares the capabilities it supports.

## Overview

The Database port in Protean provides a unified interface for different
database technologies. Each provider adapter implements this interface while
exposing the unique features of its underlying technology. Protean ships a
**memory provider**, active by default. With the memory provider, you can
develop and test your entire domain model without running any external
services.

## Available Providers

### Memory

The `memory` provider stores data in Python dictionaries. It is the default
provider and requires no external dependencies.

- **Use it for**: Development, testing, prototyping
- **Supports**: Basic storage, simulated transactions, optimistic locking, raw
  queries
- **No external dependencies required**

[Memory provider reference](./memory.md)

### PostgreSQL

The `postgresql` provider uses [SQLAlchemy](https://www.sqlalchemy.org/) to
communicate with PostgreSQL databases.

- **Use it for**: Production environments requiring full relational
  capabilities
- **Supports**: Full relational set including native JSON and array columns
- **Requires**: psycopg 3 (`protean[postgresql]`) or psycopg2 (`protean[postgresql-psycopg2]`)

[PostgreSQL provider reference](./postgresql.md)

### SQLite

The `sqlite` provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
Python's built-in `sqlite3` module.

- **Use it for**: Local development, testing with real SQL semantics
- **Supports**: Full relational set (excluding native JSON and array)
- **No external dependencies required** (SQLite is part of the Python standard
  library)

[SQLite provider reference](./sqlite.md)

### MSSQL

The `mssql` provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
[pyodbc](https://github.com/mkleehammer/pyodbc) to communicate with Microsoft
SQL Server.

- **Use it for**: Production environments on SQL Server
- **Supports**: Full relational set, including JSON and array columns
- **Requires**: `pyodbc` and a Microsoft ODBC driver installed on the machine

[MSSQL provider reference](./mssql.md)

### MySQL

The `mysql` provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
[PyMySQL](https://github.com/PyMySQL/PyMySQL) to communicate with MySQL and
MariaDB. One provider serves both servers.

- **Use it for**: Production environments on MySQL or MariaDB
- **Supports**: Full relational set plus JSON columns. MySQL has no array type,
  so a `List` field is stored as JSON
- **Requires**: `pymysql`, which installs from a wheel everywhere

[MySQL provider reference](./mysql.md)

### Elasticsearch

The `elasticsearch` provider uses the
[DSL bundled with the Elasticsearch client](https://elasticsearch-py.readthedocs.io/en/stable/dsl.html)
for document store operations.

- **Use it for**: Search and analytics workloads, document-oriented storage
- **Supports**: Basic storage, schema management, optimistic locking
- **Requires**: `elasticsearch` (8.18 or newer, which ships `elasticsearch.dsl`)

[Elasticsearch provider reference](./elasticsearch.md)

## Configuration

Providers are configured in your domain configuration file (`domain.toml` or
`.domain.toml`):

```toml
# Default database configuration (required)
[databases.default]
provider = "memory"

# Additional named databases
[databases.analytics]
provider = "elasticsearch"
database_uri = { hosts = ["http://localhost:9200"] }

[databases.reporting]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/reports"
```

Each database configuration must specify:

- `provider`: The provider adapter to use (`memory`, `postgresql`, `sqlite`,
  `mssql`, `mysql`, `elasticsearch`, or a third-party provider name)
- Additional provider-specific options (like `database_uri` for non-memory
  providers)

!!!important
    You must define a `default` database in your configuration. This database
    will be used for all aggregates unless a specific database is requested.

## Database Capabilities

Providers declare their capabilities through a flag-based system. Broker
capabilities form hierarchical tiers, but database capabilities are
**orthogonal**: each provider declares any subset of capabilities it supports.
You can combine individual flags freely.

### Capability Flags

Capabilities are organized into five tiers:

**Tier 1: Flags every provider supports**

| Flag | Description |
|------|-------------|
| `CRUD` | Create, Read, Update, Delete single records |
| `FILTER` | Query/filter records with lookup criteria |
| `BULK_OPERATIONS` | `update_all()`, `delete_all()` |
| `ORDERING` | Server-side `ORDER BY` support |

**Tier 2: Flags that protect data integrity**

| Flag | Description |
|------|-------------|
| `TRANSACTIONS` | Real commit/rollback atomicity (database-level ACID) |
| `SIMULATED_TRANSACTIONS` | Copy-on-write UoW semantics (no true rollback) |
| `OPTIMISTIC_LOCKING` | Version-based concurrency control |

**Tier 3: Flags that extend queries**

| Flag | Description |
|------|-------------|
| `RAW_QUERIES` | Execute raw/native queries (SQL, JSON criteria, DSL) |

**Tier 4: Infrastructure**

| Flag | Description |
|------|-------------|
| `SCHEMA_MANAGEMENT` | Create/drop tables, indices, or storage structures |
| `CONNECTION_POOLING` | Connection pool management |

**Tier 5: Flags for native column types**

| Flag | Description |
|------|-------------|
| `NATIVE_JSON` | Native JSON column support (e.g. PostgreSQL `JSONB`) |
| `NATIVE_ARRAY` | Native array column support (e.g. PostgreSQL `ARRAY`) |

### Convenience Sets

Common capability combinations are bundled as convenience sets:

| Set | Included Flags |
|-----|---------------|
| `BASIC_STORAGE` | CRUD, FILTER, BULK_OPERATIONS, ORDERING |
| `IN_MEMORY` | BASIC_STORAGE, SIMULATED_TRANSACTIONS, OPTIMISTIC_LOCKING, RAW_QUERIES |
| `RELATIONAL` | BASIC_STORAGE, TRANSACTIONS, OPTIMISTIC_LOCKING, RAW_QUERIES, SCHEMA_MANAGEMENT, CONNECTION_POOLING |
| `DOCUMENT_STORE` | BASIC_STORAGE, SCHEMA_MANAGEMENT, OPTIMISTIC_LOCKING |

### Checking Capabilities at Runtime

You can check provider capabilities programmatically:

```python
--8<-- "adapters/database/index/001.py:full"
```

On the memory provider, `results` holds one record, Ada's.

!!!note
    Some methods, such as `raw()`, require a specific capability and check for
    it automatically. When the provider does not declare the required
    capability, the method raises `NotSupportedError`. You only need to check
    capabilities explicitly when writing code that adapts its behavior based on
    what is available.

### Provider Capability Matrix

|  | Memory | SQLite | PostgreSQL | MSSQL | MySQL | Elasticsearch |
|— |:------:|:------:|:----------:|:-----:|:-----:|:-------------:|
| CRUD | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| FILTER | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| BULK_OPERATIONS | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| ORDERING | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| TRANSACTIONS |  | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |  |
| SIMULATED_TRANSACTIONS | :white_check_mark: |  |  |  |  |  |
| OPTIMISTIC_LOCKING | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| RAW_QUERIES | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |  |
| SCHEMA_MANAGEMENT |  | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| CONNECTION_POOLING |  | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |  |
| NATIVE_JSON |  |  | :white_check_mark: | :white_check_mark: | :white_check_mark: |  |
| NATIVE_ARRAY |  |  | :white_check_mark: | :white_check_mark: |  |  |

## Provider Registry

Providers register themselves through Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/)
under the `protean.providers` group. This means third-party database adapters
can be pip-installed and automatically discovered by Protean without any source
code changes.

### Built-in Entry Points

Protean's built-in providers are registered in `pyproject.toml`:

```toml
[project.entry-points."protean.providers"]
memory = "protean.adapters.repository.memory:register"
postgresql = "protean.adapters.repository.sqlalchemy:register_postgresql"
sqlite = "protean.adapters.repository.sqlalchemy:register_sqlite"
mssql = "protean.adapters.repository.sqlalchemy:register_mssql"
mysql = "protean.adapters.repository.sqlalchemy:register_mysql"
elasticsearch = "protean.adapters.repository.elasticsearch:register"
```

Each entry point maps a provider name to a `register()` function. Protean calls
the function on first access. The function registers the provider class path
with the `ProviderRegistry`. Each `register()` function wraps its dependencies
in `try/except`. When a provider's optional dependencies are not installed,
Protean silently skips that provider.

### Third-Party Providers

External packages can register their own providers by adding an entry point in
their `pyproject.toml`:

```toml
[project.entry-points."protean.providers"]
dynamodb = "my_package:register"
```

After `pip install my-package`, the provider becomes available:

```toml
[databases.default]
provider = "dynamodb"
database_uri = "dynamodb://localhost:8000"
```

See [Building Custom Database Adapters](./custom-databases.md) for a complete
guide.

## Required Lookups

Every provider must register a minimum set of **12 standard lookups** that
power Protean's filtering API. Protean validates these lookups when it first
loads a provider. A missing lookup produces a warning. A filter that uses a
missing lookup raises `NotImplementedError`.

| Lookup | Example |
|--------|---------|
| `exact` | `name='John'` |
| `iexact` | `name__iexact='john'` |
| `contains` | `name__contains='oh'` |
| `icontains` | `name__icontains='oh'` |
| `startswith` | `name__startswith='Jo'` |
| `endswith` | `name__endswith='hn'` |
| `gt` | `age__gt=21` |
| `gte` | `age__gte=21` |
| `lt` | `age__lt=65` |
| `lte` | `age__lte=65` |
| `in` | `status__in=['active', 'pending']` |
| `isnull` | `status__isnull=True` / `status__isnull=False` |

The `isnull` lookup resolves to `IS NULL` / `IS NOT NULL` predicates (or the
adapter's equivalent, such as Elasticsearch's `exists` query). It is required
because core framework machinery, including the outbox poll path, depends on
it.

Providers may register additional lookups beyond this required set.

## Choosing and configuring a provider

1. **A default database is required**, even if it is only the memory provider
   for development.

2. **Start with in-memory, switch later**: Develop and test with the memory
   provider, then switch to a production database by changing configuration
   only.

3. **Check capabilities before using advanced features**: Not all providers
   support raw queries, native JSON, or native array columns.

4. **Use appropriate providers for different concerns**:
    - Memory for fast unit tests
    - SQLite for local development with real SQL
    - PostgreSQL for production
    - Elasticsearch for search-heavy read models

5. **Let Protean auto-generate database models**: When you need to customize
   column types, indices, or other database-specific details, supply a custom
   `@domain.database_model`. Otherwise, leave it out.

6. **Monitor provider health**: Use `provider.is_alive()` to verify
   connectivity during health checks.

## Indexes

Aggregates and entities declare the indexes their query paths need with the
`indexes=` option (see [Indexes](../../domain-elements/indexes.md)). Every SQL
provider honors the portable subset (composite, descending, unique, and named
indexes). Where a dialect cannot support an opt-in feature, the provider
degrades that feature gracefully:

| Feature | PostgreSQL | SQLite | SQL Server | Memory | Elasticsearch |
|---------|:----------:|:------:|:----------:|:------:|:-------------:|
| Composite / `unique` / `desc` | ✅ | ✅ | ✅ | advisory | — |
| Partial (`where=`) | ✅ | ✅ | ⚠️ | advisory | — |
| Covering (`include=`) | ✅ | ⚠️ | ✅ | advisory | — |

⚠️ = falls back to a full index with a logged warning. The memory provider
validates declarations but does not enforce them.

## Related pages

- Configure a specific provider: [Memory](./memory.md),
  [SQLite](./sqlite.md), [PostgreSQL](./postgresql.md), [MSSQL](./mssql.md),
  [Elasticsearch](./elasticsearch.md)
- [Build a custom database adapter](./custom-databases.md) for other
  technologies
- [Test adapter conformance](../../testing/conformance.md) against the generic
  test suite
- Learn about [repositories and persistence](../../../guides/change-state/repositories.md)
