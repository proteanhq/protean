# MySQL

The MySQL provider uses [SQLAlchemy](https://www.sqlalchemy.org/) with
[PyMySQL](https://github.com/PyMySQL/PyMySQL) to talk to MySQL and MariaDB. One
provider serves both servers, and it is exercised by the same conformance tests
as PostgreSQL, SQLite and MSSQL.

## Installation

```bash
pip install "protean[mysql]"
```

PyMySQL is written in Python, so the extra installs from a wheel everywhere and
needs no `libmysqlclient` on the machine. The extra also installs
`cryptography`. PyMySQL needs `cryptography` for the RSA key exchange that
`caching_sha2_password` and `sha256_password` use on an unencrypted connection.

If PyMySQL cannot be imported, `domain.init()` raises a `ConfigurationError`
that names the extra to install. This covers a `database_uri` that names
PyMySQL (`mysql+pymysql://`, `mariadb+pymysql://`). SQLAlchemy connects a plain
`mysql://` or `mariadb://` through mysqlclient, so Protean checks that URL for
mysqlclient. When mysqlclient is missing, the error asks you to add `+pymysql`
to the URL and install the extra. A `database_uri` that names another
driver, such as `mysql+mysqldb://`, goes to SQLAlchemy as written.
So does a database config with a `module` key, which hands SQLAlchemy
the DBAPI module to use in place of the URL's driver.

## Configure TLS explicitly

**Do not assume the driver encrypts the connection.** Whether PyMySQL starts
TLS on its own depends on the version. On `pymysql==1.1.1`, the lowest version
this extra allows, a connection with no SSL options is plaintext, even if you
pass `ssl={}` or `ssl_disabled=False`. A current release does negotiate TLS.
Do not rely on that difference between versions.

On a plaintext connection under MySQL 8's default `caching_sha2_password`, the
driver sends the password through an RSA exchange, so set the
transport deliberately:

Add the CA to the database block, alongside the keys above:

```toml
connect_args = { ssl_ca = "/etc/ssl/certs/mysql-ca.pem" }
```

MySQL 8 generates a CA at first start, at `/var/lib/mysql/ca.pem` on the
server. Verify the connection rather than trusting the config:

```sql
SHOW STATUS LIKE 'Ssl_cipher';
```

An empty value means the connection is in the clear.

## Configuration

```toml
[databases.default]
provider = "mysql"
database_uri = "mysql+pymysql://app:${MYSQL_PASSWORD}@localhost:3306/appdb"
```

For MariaDB, use the `mariadb+pymysql://` scheme:

```toml
[databases.default]
provider = "mysql"
database_uri = "mariadb+pymysql://app:${MYSQL_PASSWORD}@localhost:3306/appdb"
```

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"mysql"`, for MySQL and for MariaDB |
| `database_uri` | Required | PyMySQL connection string |
| `collation` | per dialect (see below) | Default collation of created tables; must be a `utf8mb4_` collation |
| `pool_size` | 5 | Connections held open in the pool |
| `max_overflow` | 10 | Connections opened beyond `pool_size` under load |

Use the scheme that matches the server. SQLAlchemy reports the dialect as
`mysql` for `mysql+pymysql://` and `mariadb` for `mariadb+pymysql://`. The
provider reads the dialect name to decide how to emit table DDL. Pointing a
`mysql+pymysql://` URI at a MariaDB server works, but the DDL is written for
MySQL.

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
- :white_check_mark: **SCHEMA_MIGRATIONS**: Versioned migrations through Alembic.
- :white_check_mark: **NATIVE_JSON**: `Dict` fields map to the `JSON` column type.
- :x: **NATIVE_ARRAY**: MySQL has no array type. A `List` field is stored as
  JSON, which is what the MSSQL provider does too.

## Collation and case sensitivity

MySQL 8 defaults to `utf8mb4_0900_ai_ci` and MariaDB to
`utf8mb4_uca1400_ai_ci`. Both ignore case and accents, so on a table that takes
the server default, `exact`, `contains`, `startswith` and `endswith` would all
match rows they should not. Every other Protean provider compares strings
case-sensitively.

The provider therefore creates each table with an explicit accent- and
case-sensitive collation, which every string column in the table inherits:

```sql
-- MySQL
CREATE TABLE person (...) CHARSET=utf8mb4 COLLATE utf8mb4_0900_as_cs
-- MariaDB
CREATE TABLE person (...) CHARSET=utf8mb4 COLLATE utf8mb4_uca1400_as_cs
```

The provider sets the collation on the table instead of on each lookup, so
MySQL can still use indexes. A `COLLATE` applied to a column inside a `WHERE`
clause stops the optimizer from using an index on that column, and Protean
filters through these lookups constantly.

Two consequences:

- Protean sets the collation only on the tables it creates. A table created by
  hand, or by an earlier migration, keeps whatever collation it was given, and
  string lookups against it behave the way that collation says.
- MySQL and MariaDB spell the accent- and case-sensitive collation differently,
  so the default follows the dialect: `utf8mb4_0900_as_cs` on MySQL,
  `utf8mb4_uca1400_as_cs` on MariaDB. Neither name is a safe default for both.
  MySQL has never had a `uca1400` collation. MariaDB added the `utf8mb4_0900_*`
  aliases only in 11.4.5, so MariaDB 10.11 LTS and 11.4.4 refuse the MySQL name
  with `Unknown collation`. MySQL needs 8.0.1+ and MariaDB needs 10.10+; on
  anything older, set `collation = "utf8mb4_bin"`.

The charset is pinned to `utf8mb4` and is not configurable: a narrower charset
cannot hold the 4-byte characters Protean stores. MySQL names a collation after
its charset and rejects a mismatched pair. Protean therefore refuses a
`collation` from another charset at `domain.init()` with an error that names
the config key, before MySQL can refuse it at `CREATE TABLE` with its
own message.

The case-insensitive lookups (`iexact`, `icontains`) are unaffected: they lower
both sides of the comparison, so they keep matching every case.

The provider sets `mysql_charset`, `mysql_collate`, `mysql_engine` and
`mysql_row_format` itself. A [custom database model](../../../guides/change-state/database-models.md)
keeps every other table kwarg it declares. The charset and the collation must
match. If a model set only the charset, the table would get the provider's
collation with a different character set, and MySQL rejects that pair
at `CREATE TABLE`.

## Isolation level

InnoDB defaults to `REPEATABLE READ`, under which a transaction keeps reading
the snapshot it opened with. [ADR-0027](../../../adr/0027-unit-of-work-is-a-real-transaction.md)
makes a Unit of Work one real database transaction and expects a read inside it
to see what other transactions have committed. PostgreSQL and SQL Server behave
that way at their default isolation levels. The provider therefore opens its
engine at `READ COMMITTED`.

## Schema changes commit the open transaction

MySQL has no transactional DDL. A `CREATE TABLE`, `ALTER TABLE` or `DROP TABLE`
commits whatever the connection has pending. `protean db setup` runs its DDL on
a connection of its own, outside any Unit of Work, so ordinary use is
unaffected. If you run DDL inside a Unit of Work, MySQL commits that Unit of
Work's writes early, and a later rollback does not undo them.

## String columns used as keys

InnoDB caps an index key at 3072 bytes. A `utf8mb4` character takes up to four
bytes, so InnoDB cannot index a `VARCHAR` beyond 768 characters in full. A
primary key or a unique constraint needs a full index. Protean raises
`IncorrectUsageError` naming the field at schema-generation time:

```python
--8<-- "adapters/database/mysql/001.py:key_columns"
```

A `String` field with `max_length=None` becomes a `TEXT` column, because MySQL
cannot create a `VARCHAR` without a length. A `TEXT` column cannot be a key
column without an index prefix length either, so a key on a `String` field with
`max_length=None` raises the same error. A `ValueObjectList(..., pickled=True)`
is stored as a BLOB, which has the same problem, so `unique=True` on one
raises too.

The cap applies to a declared [`Index`](../../domain-elements/indexes.md) too,
and InnoDB measures the whole key, so a composite index is the sum of its string
columns:

```python
--8<-- "adapters/database/mysql/001.py:composite_index"
```

Each field fits on its own; together they overrun the key.

Every column in the key counts, not only the strings. Only a string column is
wide enough to reach 3072 bytes alone, but a fixed-width column next to a
string near the limit can push the key past 3072 bytes. For example,
`String(max_length=768)` uses exactly 3072 bytes, and `Index("slug", "rank")`
with an `Integer` needs 3076 bytes. The widths are the column's storage size,
measured against both servers:

| Field | Column | Bytes |
|-------|--------|------:|
| `String(max_length=n)` | `VARCHAR(n)` | `4 * n` |
| a `TEXT` or `BLOB` column | not indexable without a prefix | raises |
| `Boolean` | `TINYINT` | 1 |
| `Date` | `DATE` | 3 |
| `Integer` | `INT` | 4 |
| `Float` | `FLOAT` | 4 |
| a `DOUBLE` or `REAL` column | `DOUBLE` | 8 |
| `DateTime` | `DATETIME(6)` | 8 |
| `Decimal(precision, scale)` | `DECIMAL` | 4 per 9 digits |
| Identity, and any reference to one | `CHAR(32)`, `VARCHAR(255)` or `INT` | 128, 1020 or 4 |

The check counts a type missing from this table as zero bytes instead of
guessing its width. So a key that goes over the limit because of such a type
still gets MySQL's own error.

An index may name a value object's shadow column (`Index("address_city")` for a
`city` field on an embedded `Address`), and those are measured the same way,
from the value object's own field.

An association column holds the referenced aggregate's identity, so it has the
width of that identity column. That width is `CHAR(32)` under a UUID identity
and `VARCHAR(255)` under a string one. Both count toward the key.

A [custom database model](../../../guides/change-state/database-models.md)
declares its own columns. InnoDB applies the cap to those declared columns. So
when an aggregate has a custom model, the check reads each width from the
column the model declares and not from the field. A model that narrows
`String(max_length=900)` to `Column(String(100))` indexes fine, and one that
widens a short field past the cap raises. `protean schema render` cannot see
those columns, so it skips the check for an aggregate with a custom model and
leaves it to `protean db setup`.

`protean schema render --indexes` runs the same check for the `mysql` and
`mariadb` dialects, so a rendered `.sql` file never carries DDL the server would
reject on apply.

## Storage engine and row format

The provider creates tables with `ENGINE=InnoDB ROW_FORMAT=DYNAMIC` stated
explicitly instead of taking the server defaults, because two of the provider's
guarantees depend on these settings.

A MyISAM table is not transactional at all, and
[ADR-0027](../../../adr/0027-unit-of-work-is-a-real-transaction.md) makes the
Unit of Work one real transaction. `default_storage_engine` is an operator
setting, so a server set to MyISAM would give you non-transactional tables
without any warning.

The 3072-byte index key limit above is the `DYNAMIC` and `COMPRESSED` figure.
Under `COMPACT` or `REDUNDANT` the limit is 767 bytes.
`innodb_default_row_format` is an operator setting too, so on a server with
either row format the key-width guard would pass an index the server
then refuses.

## Timestamps

MySQL's `DATETIME` carries zero fractional-second digits unless the column says
otherwise, and drops microseconds on write without an error. Protean writes
microsecond-precision timestamps, so every `DateTime` field maps to
`DATETIME(6)`.

A `DateTime` column holds no UTC offset, so Protean converts each value to UTC
before it writes the value or compares it in a filter. Protean reads a naive
value as UTC. A load returns a UTC-aware `datetime`. A filter value in any
offset then matches the same instant. Rows written before 0.18.1 hold the
wall-clock time they were saved with; see
[Datetimes are compared and stored as UTC](../../migration/v0-18.md#datetimes-are-compared-and-stored-as-utc)
to convert them.

## Indexes

MySQL supports some of the [`Index`](../../domain-elements/indexes.md) options
when `protean db setup` creates the indexes:

- Composite, descending (`desc=`), and unique (`unique=`) indexes.
- Partial indexes (`where=Q(...)`) are **not** supported. The index is created
  without the predicate and a warning is logged.
- Covering columns (`include=`) are **not** supported. The index is created
  without them and a warning is logged.
- A `Dict` or `List` field maps to a `JSON` column, and MySQL indexes one only
  through a generated column on a JSON path. Protean does not emit generated
  columns, so an `Index` over such a field raises `IncorrectUsageError`, as
  does `unique=True` on one. Index a scalar field instead.

`protean schema render --indexes --dialects mysql` (or `mariadb`) writes the
`CREATE INDEX` statements to `.sql` files without touching a database.

## Outbox claim

The outbox claims messages through the portable path: a bounded `SELECT`
followed by a guarded `UPDATE ... WHERE` per row. MySQL has `SKIP LOCKED` but
no `UPDATE ... RETURNING`, so the single-statement claim PostgreSQL uses does
not compile here. InnoDB re-evaluates the predicate of a guarded `UPDATE`
against committed state under row-lock contention.
[ADR-0013](../../../adr/0013-optimistic-concurrency-and-claim-contract.md)
covers why the portable path is correct on any database that does this. The
cost is `1 + N` round trips instead of one. When the outbox holds back a
partition key's rows (see
[`sequential_by`](../../server/sequential-by.md#how-the-outbox-keeps-a-key-in-order)),
each candidate row with both a partition key and a stream category adds one
more query. That query checks for an earlier row of the same key. The `SELECT`
leaves out rows that are held, so a halted key's backlog adds no queries.

The bounded delete in `_delete_top` also takes the portable path, because MySQL
rejects a `DELETE` whose subquery reads the same table.

## SQLAlchemy model

You can supply a custom SQLAlchemy model in place of the one Protean generates,
which gives you control over column types and constraints. The pattern is the
same as for [PostgreSQL](./postgresql.md#sqlalchemy-model).

```python
# fragment
--8<-- "adapters/database/mysql/002.py:full"
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

- [PostgreSQL](./postgresql.md): The full-capability relational provider,
  including native arrays.
- [MSSQL](./mssql.md): The other provider that stores lists as JSON.
- [Database capabilities](./index.md#database-capabilities): What each
  capability flag means.
- [Indexes](../../domain-elements/indexes.md): Declaring indexes on an aggregate.
