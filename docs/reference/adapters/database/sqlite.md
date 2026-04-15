# SQLite

The SQLite provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
Python's built-in `sqlite3` module to provide a file-based relational database.

## Overview

SQLite is a good choice when you need real SQL semantics without running a
separate database server. It is useful for:

- **Local development** with real transactions and SQL queries
- **Testing** when you need ACID guarantees but want to avoid Docker services
- **Single-user applications** or embedded scenarios

Because SQLite is part of the Python standard library, no additional packages
are needed beyond Protean's SQLAlchemy dependency.

## Installation

SQLite support is included with Protean's SQLAlchemy integration. If SQLAlchemy
is installed, SQLite is available automatically:

```bash
pip install "protean[postgresql]"  # Includes SQLAlchemy
# -- or --
pip install sqlalchemy
```

## Configuration

```toml
[databases.default]
provider = "sqlite"
database_uri = "sqlite:///app.db"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"sqlite"` for the SQLite provider |
| `database_uri` | Required | SQLite connection string |

### Connection String Formats

```
sqlite:///relative/path/to/file.db   # Relative path
sqlite:////absolute/path/to/file.db  # Absolute path (note four slashes)
sqlite://                             # In-memory SQLite (lost on close)
sqlite:///test.db                     # File in current directory
```

## Capabilities

The SQLite provider supports the following capabilities:

- :white_check_mark: **CRUD** -- Create, Read, Update, Delete single records
- :white_check_mark: **FILTER** -- Query/filter records with lookup criteria
- :white_check_mark: **BULK_OPERATIONS** -- `update_all()`, `delete_all()`
- :white_check_mark: **ORDERING** -- Server-side `ORDER BY` support
- :white_check_mark: **TRANSACTIONS** -- Real commit/rollback atomicity
- :white_check_mark: **OPTIMISTIC_LOCKING** -- Version-based concurrency control
- :white_check_mark: **RAW_QUERIES** -- Execute raw SQL queries
- :white_check_mark: **SCHEMA_MANAGEMENT** -- Create/drop tables
- :white_check_mark: **CONNECTION_POOLING** -- SQLAlchemy connection pool management
- :x: **SIMULATED_TRANSACTIONS** -- Uses real transactions instead
- :x: **NATIVE_JSON** -- No native JSON column type (stored as text)
- :x: **NATIVE_ARRAY** -- No native array column type (stored as text)

## SQLAlchemy Model

You can supply a custom SQLAlchemy Model in place of the one that Protean
generates internally, allowing full customization of column types and
constraints. The pattern is identical to
[PostgreSQL models](./postgresql.md#sqlalchemy-model).

```python
import sqlalchemy as sa
from protean.adapters.repository.sqlalchemy import SqlalchemyModel

@domain.aggregate
class User:
    name: String(max_length=100)
    email: String(max_length=255)

@domain.database_model(part_of=User)
class UserModel:
    name = sa.Column(sa.String(100))
    email = sa.Column(sa.String(255), unique=True)
```

!!!note
    The column names specified in the model should exactly match the attribute
    names of the Aggregate or Entity it represents.

## Slow Query Detection

The SQLAlchemy-based SQLite provider emits the same structured
``protean.adapters.repository.sqlalchemy.slow_query`` WARNING and
``protean.adapters.repository.sqlalchemy.query`` DEBUG events as the
[PostgreSQL provider](./postgresql.md#slow-query-detection). Configure the
threshold via ``[logging].slow_query_threshold_ms`` in ``domain.toml``.

## Limitations

- **Single-Writer Concurrency** -- SQLite supports only one writer at a time.
  Concurrent writes from multiple processes will block or fail.
- **No Native JSON/Array** -- Complex fields (JSON, arrays) are stored as
  serialized text. Queries cannot filter on nested JSON properties.
- **Not Suitable for Multi-Process Production** -- SQLite is designed for
  single-process use. Use PostgreSQL for production deployments.
- **File Locking** -- The database file must be on a local filesystem. Network
  filesystems (NFS, SMB) are not reliable with SQLite.

## Next Steps

- Learn about [PostgreSQL](./postgresql.md) for production environments
- Understand [database capabilities](./index.md#database-capabilities) in
  detail
- Learn about [custom SQLAlchemy models](./postgresql.md#sqlalchemy-model)
