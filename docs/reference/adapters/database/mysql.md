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
needs no `libmysqlclient` on the machine. The extra pulls `cryptography` with
it, which PyMySQL needs for the RSA key exchange that `caching_sha2_password`
and `sha256_password` use on an unencrypted connection.

## Configure TLS explicitly

**Do not assume the driver encrypts the connection.** Whether PyMySQL starts
TLS without being told to depends on the version: on `pymysql==1.1.1`, the
floor this extra declares, a connection with no SSL options is plaintext, and
passing `ssl={}` or `ssl_disabled=False` does not change that. A current
release does negotiate TLS. Pin nothing on that difference.

On a plaintext connection the password crosses the wire under MySQL 8's
default `caching_sha2_password` through an RSA exchange, so the transport is
worth setting deliberately:

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
`mysql` for `mysql+pymysql://` and `mariadb` for `mariadb+pymysql://`, and the
provider reads that name to decide how to emit table DDL. Pointing a
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

Setting the collation on the table rather than on each lookup keeps indexes
usable. A `COLLATE` applied to a column inside a `WHERE` clause stops the
optimizer from using an index on that column, and Protean filters through these
lookups constantly.

Two consequences:

- The collation only reaches tables Protean creates. A table created by hand,
  or by an earlier migration, keeps whatever collation it was given, and string
  lookups against it behave the way that collation says.
- The two servers spell that collation differently, so the default follows the
  dialect: `utf8mb4_0900_as_cs` on MySQL, `utf8mb4_uca1400_as_cs` on MariaDB.
  Neither name is a safe default for both. MySQL has never had a `uca1400`
  collation, and MariaDB only gained the `utf8mb4_0900_*` aliases in 11.4.5,
  so 10.11 LTS and 11.4.4 refuse the MySQL name with `Unknown collation`.
  MySQL needs 8.0.1+ and MariaDB needs 10.10+; on anything older, set
  `collation = "utf8mb4_bin"`.

The charset is pinned to `utf8mb4` and is not configurable: a narrower charset
cannot hold the 4-byte characters Protean stores. MySQL names a collation after
the charset it belongs to and rejects a mismatched pair, so a `collation` from
another charset is refused at `domain.init()` naming the config key, rather than
at `CREATE TABLE` with MySQL's own message.

The case-insensitive lookups (`iexact`, `icontains`) are unaffected: they lower
both sides of the comparison, so they keep matching every case.

A [custom database model](../../../guides/change-state/database-models.md) keeps
every table kwarg it declares except `mysql_charset`, `mysql_collate`,
`mysql_engine` and `mysql_row_format`, which the provider owns. The two have to agree, and a model that set only the charset
would get the provider's collation over a different character set, which MySQL
rejects at `CREATE TABLE`.

## Isolation level

InnoDB defaults to `REPEATABLE READ`, under which a transaction keeps reading
the snapshot it opened with. [ADR-0027](../../../adr/0027-unit-of-work-is-a-real-transaction.md)
makes a Unit of Work one real database transaction and expects a read inside it
to see what other transactions have committed, which is what PostgreSQL and SQL
Server do at their defaults. The provider therefore opens its engine at
`READ COMMITTED`.

## Schema changes commit the open transaction

MySQL has no transactional DDL. A `CREATE TABLE`, `ALTER TABLE` or `DROP TABLE`
commits whatever the connection has pending. `protean db setup` runs its DDL on
a connection of its own, outside any Unit of Work, so ordinary use is
unaffected. Running DDL inside a Unit of Work will commit that Unit of Work's
writes early, and a later rollback will not take them back.

## String columns used as keys

InnoDB caps an index key at 3072 bytes. A `utf8mb4` character takes up to four
bytes, so a `VARCHAR` beyond 768 characters cannot be indexed in full, which is
what a primary key or a unique constraint needs. Protean raises
`IncorrectUsageError` naming the field at schema-generation time:

```python
@domain.aggregate
class User:
    email: String(max_length=255, unique=True)   # fine
    bio: String(max_length=4000)                 # fine, not a key column
    token: String(max_length=1000, unique=True)  # raises: past the key limit
```

A `String` field with no `max_length` becomes a `TEXT` column, because MySQL
cannot create a `VARCHAR` without a length. `TEXT` cannot be a key column
either without an index prefix length, so that combination raises the same
error.

The cap applies to a declared [`Index`](../../domain-elements/indexes.md) too,
and InnoDB measures the whole key, so a composite index is the sum of its string
columns:

```python
@domain.aggregate(indexes=[Index("tenant", "slug")])
class Document:
    tenant: String(max_length=500)   # 2000 bytes
    slug: String(max_length=500)     # 2000 bytes, and 4000 together: raises
```

Each field fits on its own; together they overrun the key.

Every column in the key counts, not just the strings. A string is the only one
wide enough to reach 3072 bytes alone, but a fixed-width column alongside a
near-limit string is what tips it over: `String(max_length=768)` fills the
budget exactly, and `Index("slug", "rank")` with an `Integer` needs 3076. The
widths are the column's storage size, measured against both servers:

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

A type not in this table counts as nothing rather than as a guess, so a key
that overruns on one still gets MySQL's own error.

An index may name a value object's shadow column (`Index("address_city")` for a
`city` field on an embedded `Address`), and those are measured the same way,
from the value object's own field.

An association column holds the referenced aggregate's identity, so it is that
column's width: `CHAR(32)` under a UUID identity, `VARCHAR(255)` under a string
one. Both count toward the key.

A [custom database model](../../../guides/change-state/database-models.md)
declares its own columns, and InnoDB caps the column. So when an aggregate has
one, the width comes from the column the model declares, not from the field. A
model that narrows `String(max_length=900)` to `Column(String(100))` indexes
fine, and one that widens a short field past the cap raises. `protean schema
render` cannot see those columns, so it skips the check for an aggregate with a
custom model and leaves it to `protean db setup`.

`protean schema render --indexes` runs the same check for the `mysql` and
`mariadb` dialects, so a rendered `.sql` file never carries DDL the server would
reject on apply.

## Storage engine and row format

Tables are created `ENGINE=InnoDB ROW_FORMAT=DYNAMIC`, named rather than taken
from the server, because two of the provider's guarantees rest on them.

A MyISAM table is not transactional at all, and
[ADR-0027](../../../adr/0027-unit-of-work-is-a-real-transaction.md) makes the
Unit of Work one real transaction. `default_storage_engine` is an operator
setting, so a server set to MyISAM would give you non-transactional tables with
nothing to say so.

The 3072-byte index key limit above is the `DYNAMIC` and `COMPRESSED` figure.
Under `COMPACT` or `REDUNDANT` it is 767 bytes, and `innodb_default_row_format`
is an operator setting too, so on such a server the key-width guard would pass
an index the server then refuses.

## Timestamps

MySQL's `DATETIME` carries zero fractional-second digits unless the column says
otherwise, and drops microseconds on write without an error. Protean writes
microsecond-precision timestamps, so every `DateTime` field maps to
`DATETIME(6)`.

## Indexes

MySQL honors part of the [`Index`](../../domain-elements/indexes.md) surface,
emitted during `protean db setup`:

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
not compile here. [ADR-0013](../../../adr/0013-optimistic-concurrency-and-claim-contract.md)
covers why the portable path is correct wherever a guarded `UPDATE` re-evaluates
its predicate against committed state under row-lock contention, which InnoDB
does. The cost is `1 + N` round trips instead of one.

The bounded delete behind `_delete_top` takes the portable path for the same
kind of reason: MySQL rejects a subquery that reads the table being deleted
from.

## SQLAlchemy model

You can supply a custom SQLAlchemy model in place of the one Protean generates,
which gives you control over column types and constraints. The pattern is the
same as for [PostgreSQL](./postgresql.md#sqlalchemy-model).

```python
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

@domain.aggregate
class User:
    name: String(max_length=100)
    preferences: Dict()

@domain.database_model(part_of=User)
class UserModel:
    name = sa.Column(mysql.VARCHAR(100))
    preferences = sa.Column(mysql.JSON)
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
