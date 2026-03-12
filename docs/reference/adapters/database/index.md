# Database Providers

Database providers abstract the underlying persistence technology, allowing
Protean to support various databases without changing domain or application
logic. Each provider implements the `BaseProvider` interface and declares the
capabilities it supports.

## Overview

The Database port in Protean provides a unified interface for different database
technologies. Each provider adapter implements this interface while exposing the
unique features of its underlying technology. Protean ships a
**memory provider** that is active by default, so you can develop and test your
entire domain model without running any external services.

## Available Providers

### Memory

The `memory` provider stores data in Python dictionaries. It is the default
provider and requires no external dependencies.

- **Use cases**: Development, testing, prototyping
- **Capabilities**: Basic storage, simulated transactions, optimistic locking,
  raw queries
- **No external dependencies required**

[Memory provider reference](./memory.md)

### PostgreSQL

The `postgresql` provider uses [SQLAlchemy](https://www.sqlalchemy.org/) to
communicate with PostgreSQL databases.

- **Use cases**: Production environments requiring full relational capabilities
- **Capabilities**: Full relational set including native JSON and array columns
- **Requires**: `psycopg2-binary` or `psycopg2`

[PostgreSQL provider reference](./postgresql.md)

### SQLite

The `sqlite` provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
Python's built-in `sqlite3` module.

- **Use cases**: Local development, testing with real SQL semantics
- **Capabilities**: Full relational set (excluding native JSON and array)
- **No external dependencies required** (SQLite is part of the Python standard
  library)

[SQLite provider reference](./sqlite.md)

### Elasticsearch

The `elasticsearch` provider uses
[elasticsearch-dsl](https://elasticsearch-dsl-py.readthedocs.io/) for document
store operations.

- **Use cases**: Search and analytics workloads, document-oriented storage
- **Capabilities**: Basic storage, schema management, optimistic locking
- **Requires**: `elasticsearch` and `elasticsearch-dsl`

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
database_uri = "{'hosts': ['localhost']}"

[databases.reporting]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/reports"
```

Each database configuration must specify:

- `provider`: The provider adapter to use (`memory`, `postgresql`, `sqlite`,
  `elasticsearch`, or a third-party provider name)
- Additional provider-specific options (like `database_uri` for non-memory
  providers)

!!!important
    You must define a `default` database in your configuration. This database
    will be used for all aggregates unless a specific database is requested.

## Database Capabilities

Providers declare their capabilities through a flag-based system. Unlike broker
capabilities (which are hierarchical tiers), database capabilities are
**orthogonal** -- providers pick and choose which capabilities they support, and
individual flags can be combined freely.

### Capability Flags

Capabilities are organized into five tiers:

**Tier 1: Universal Foundation** -- Every provider supports these.

| Flag | Description |
|------|-------------|
| `CRUD` | Create, Read, Update, Delete single records |
| `FILTER` | Query/filter records with lookup criteria |
| `BULK_OPERATIONS` | `update_all()`, `delete_all()` |
| `ORDERING` | Server-side `ORDER BY` support |

**Tier 2: Data Integrity**

| Flag | Description |
|------|-------------|
| `TRANSACTIONS` | Real commit/rollback atomicity (database-level ACID) |
| `SIMULATED_TRANSACTIONS` | Copy-on-write UoW semantics (no true rollback) |
| `OPTIMISTIC_LOCKING` | Version-based concurrency control |

**Tier 3: Query Power**

| Flag | Description |
|------|-------------|
| `RAW_QUERIES` | Execute raw/native queries (SQL, JSON criteria, DSL) |

**Tier 4: Infrastructure**

| Flag | Description |
|------|-------------|
| `SCHEMA_MANAGEMENT` | Create/drop tables, indices, or storage structures |
| `CONNECTION_POOLING` | Connection pool management |

**Tier 5: Type System**

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
from protean.port.provider import DatabaseCapabilities

# Get the default provider
provider = domain.providers["default"]

# Check for a single capability
if provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
    results = provider.raw("SELECT * FROM users WHERE age > 21")

# Check for all of multiple capabilities (AND logic)
if provider.has_all_capabilities(
    DatabaseCapabilities.NATIVE_JSON | DatabaseCapabilities.NATIVE_ARRAY
):
    # Use native JSON and array columns
    ...

# Check for any of multiple capabilities (OR logic)
if provider.has_any_capability(
    DatabaseCapabilities.TRANSACTIONS | DatabaseCapabilities.SIMULATED_TRANSACTIONS
):
    # Some form of transaction support is available
    ...
```

!!!note
    Methods that require a specific capability (like `raw()`) automatically
    check for it and raise `NotSupportedError` if the provider does not declare
    the required capability. You only need to check capabilities explicitly when
    writing code that adapts its behavior based on what is available.

### Provider Capability Matrix

|  | Memory | SQLite | PostgreSQL | Elasticsearch |
|--|:------:|:------:|:----------:|:-------------:|
| CRUD | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| FILTER | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| BULK_OPERATIONS | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| ORDERING | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| TRANSACTIONS | | :white_check_mark: | :white_check_mark: | |
| SIMULATED_TRANSACTIONS | :white_check_mark: | | | |
| OPTIMISTIC_LOCKING | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| RAW_QUERIES | :white_check_mark: | :white_check_mark: | :white_check_mark: | |
| SCHEMA_MANAGEMENT | | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| CONNECTION_POOLING | | :white_check_mark: | :white_check_mark: | |
| NATIVE_JSON | | | :white_check_mark: | |
| NATIVE_ARRAY | | | :white_check_mark: | |

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
elasticsearch = "protean.adapters.repository.elasticsearch:register"
```

Each entry point maps a provider name to a `register()` function. The function
is called on first access and registers the provider class path with the
`ProviderRegistry`. Dependencies are wrapped in `try/except` so that providers
with uninstalled optional dependencies are silently skipped.

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

Every provider must register a minimum set of **11 standard lookups** that
power Protean's filtering API. These are validated when a provider is first
loaded -- missing lookups produce a warning, and filters using them will raise
`NotImplementedError`.

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

Providers may register additional lookups beyond this required set.

## Best Practices

1. **Always define a default database** -- Even if it is just the memory
   provider for development.

2. **Start with in-memory, switch later** -- Develop and test with the memory
   provider, then switch to a production database by changing configuration
   only.

3. **Check capabilities before using advanced features** -- Not all providers
   support raw queries, native JSON, or native array columns.

4. **Use appropriate providers for different concerns**:
    - Memory for fast unit tests
    - SQLite for local development with real SQL
    - PostgreSQL for production
    - Elasticsearch for search-heavy read models

5. **Let Protean auto-generate database models** -- Only supply a custom
   `@domain.model` when you need to customize column types, indices, or other
   database-specific details.

6. **Monitor provider health** -- Use `provider.is_alive()` to verify
   connectivity during health checks.

## Next Steps

- Configure a specific provider: [Memory](./memory.md),
  [SQLite](./sqlite.md), [PostgreSQL](./postgresql.md),
  [Elasticsearch](./elasticsearch.md)
- [Build a custom database adapter](./custom-databases.md) for other
  technologies
- [Test adapter conformance](../../testing/conformance.md) against the generic
  test suite
- Learn about [repositories and persistence](../../../guides/change-state/repositories.md)
