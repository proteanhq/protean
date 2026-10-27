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

If pyodbc cannot be imported, `domain.init()` raises a `ConfigurationError`
that names the extra to install. This covers a `database_uri` that names pyodbc
(`mssql+pyodbc://`) and one that names no driver (`mssql://`). pyodbc
installed without the unixODBC system library fails to import, so it fails the
same way. A `database_uri` that names another driver, such as
`mssql+pymssql://`, goes to SQLAlchemy as written.
So does a database config with a `module` key, which hands SQLAlchemy
the DBAPI module to use in place of the URL's driver.

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
--8<-- "adapters/database/mssql/002.py:key_columns"
```

`String()` has a default `max_length` of 255, so it is a valid key column. The
error comes from a column with no length, such as `max_length=None`. A column
with no length is fine on MSSQL as an ordinary column. Protean raises only when
that column is a primary key or is `unique=True`.

## Date and time columns

| Field      | Column      |
|------------|-------------|
| `DateTime` | `DATETIME2` |
| `Date`     | `DATE`      |

SQL Server's `DATETIME` rounds to increments of about 3 milliseconds: the last
digit of the milliseconds becomes 0, 3 or 7, so `.125` is stored as `.127`.
Protean writes microsecond-precision timestamps, so two values written less
than 3 ms apart could read back equal, and a value read back could differ from
the one written. `DATETIME2` keeps 100-nanosecond steps, so every `DateTime`
column Protean generates uses it.

A table created before 0.19 keeps its `DATETIME` columns, because Protean does
not change an existing table. See
[SQL Server stores `DateTime` as `DATETIME2`](../../migration/v0-19.md#sql-server-stores-datetime-as-datetime2)
for the statements that convert them.

## SQLAlchemy model

You can supply a custom SQLAlchemy model in place of the one Protean generates,
which gives you control over column types and constraints. The pattern is the
same as for [PostgreSQL](./postgresql.md#sqlalchemy-model).

```python
# fragment
--8<-- "adapters/database/mssql/001.py:full"
```

!!!note
    Column names in the model must match the attribute names of the aggregate
    or entity they represent.

A column you declare in the model keeps the type you give it. Declare a
timestamp column as `DATETIME2` (`sqlalchemy.dialects.mssql.DATETIME2`) to keep
microseconds.

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
