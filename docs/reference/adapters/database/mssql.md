# MSSQL

The MSSQL provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
[pyodbc](https://github.com/mkleehammer/pyodbc) to talk to Microsoft SQL Server.
It carries the same capability set as the PostgreSQL provider and is exercised
by the same conformance tests.

## Installation

The provider needs SQLAlchemy, pyodbc, and a Microsoft ODBC driver installed on
the machine:

```bash
pip install "protean[mssql]"
```

pyodbc is a binding, not a driver. Install
[Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
separately through your operating system's package manager.

## Configuration

```toml
[databases.default]
provider = "mssql"
database_uri = "mssql+pyodbc://sa:${MSSQL_PASSWORD}@localhost:1433/appdb?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=yes&MARS_Connection=yes"
```

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"mssql"` |
| `database_uri` | Required | pyodbc connection string, including the `driver` query parameter |
| `schema` | `dbo` | Schema that tables are created in |
| `pool_size` | SQLAlchemy default | Connections held open in the pool |
| `max_overflow` | SQLAlchemy default | Connections opened beyond `pool_size` under load |

The `driver` query parameter is required: pyodbc has no default driver, and
omitting it fails at connection time rather than at `domain.init()`.
`MARS_Connection=yes` lets one connection hold several active result sets,
which the provider relies on when a repository iterates one query while issuing
another.

## Capabilities

- :white_check_mark: **CRUD**: Create, read, update, delete single records.
- :white_check_mark: **FILTER**: Query and filter records with lookup criteria.
- :white_check_mark: **BULK_OPERATIONS**: `update_all()` and `delete_all()`.
- :white_check_mark: **ORDERING**: Server-side `ORDER BY`.
- :white_check_mark: **TRANSACTIONS**: Real commit and rollback atomicity.
- :white_check_mark: **OPTIMISTIC_LOCKING**: Version-based concurrency control.
- :white_check_mark: **RAW_QUERIES**: Execute raw SQL.
- :white_check_mark: **SCHEMA_MANAGEMENT**: Create and drop tables.
- :white_check_mark: **CONNECTION_POOLING**: SQLAlchemy pool management.
- :white_check_mark: **NATIVE_JSON** and **NATIVE_ARRAY**: `Dict` and `List`
  fields are queryable. SQL Server has no `JSON` column type, so the provider
  stores them through a JSON type backed by `NVARCHAR`.

## Indexes

MSSQL honors part of the [`Index`](../../domain-elements/indexes.md) surface,
emitted during `protean db setup`:

- Composite, descending (`desc=`), and unique (`unique=`) indexes.
- Covering columns (`include=`), which map to SQL Server's `INCLUDE` clause.
- Partial indexes (`where=Q(...)`) are **not** supported. The index is created
  without the predicate and a warning is logged.

## String columns used as keys

SQL Server rejects an unbounded `VARCHAR` in a primary key or a unique
constraint. Protean catches this at schema-generation time and raises
`IncorrectUsageError` naming the field, instead of letting the database fail
with its own message about a column being invalid as a key:

```python
@domain.aggregate
class User:
    email: String(max_length=255, unique=True)  # length is required here
```

A `String` field without `max_length` is fine on MSSQL as an ordinary column.
The length is only required when the column is a primary key, is `unique=True`,
or takes part in a unique index.

## SQLAlchemy model

You can supply a custom SQLAlchemy model in place of the one Protean generates,
which gives you control over column types and constraints. The pattern is the
same as for [PostgreSQL](./postgresql.md#sqlalchemy-model).

```python
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

@domain.aggregate
class User:
    name: String(max_length=100)
    email: String(max_length=255)

@domain.database_model(part_of=User)
class UserModel:
    name = sa.Column(mssql.NVARCHAR(100))
    email = sa.Column(mssql.NVARCHAR(255), unique=True)
```

!!!note
    Column names in the model must match the attribute names of the aggregate
    or entity they represent.

## Slow query detection

The provider emits the same structured
`protean.adapters.repository.sqlalchemy.slow_query` WARNING and
`protean.adapters.repository.sqlalchemy.query` DEBUG events as the
[PostgreSQL provider](./postgresql.md#slow-query-detection). Set the threshold
with `[logging].slow_query_threshold_ms` in `domain.toml`.

## Related pages

- [PostgreSQL](./postgresql.md): The other full-capability relational provider.
- [Database capabilities](./index.md#database-capabilities): What each
  capability flag means.
- [Indexes](../../domain-elements/indexes.md): Declaring indexes on an aggregate.
