# Custom Database Adapters

Learn how to create custom database adapters for Protean to integrate with any
persistence technology.

## Overview

Custom database adapters allow you to:

- Integrate new database technologies (DynamoDB, MongoDB, CockroachDB, etc.)
- Add company-specific storage systems
- Create specialized adapters for testing or development

## Architecture

All database adapters are built from five components that work together:

### 1. Provider

**Extends**: `protean.port.database.BaseDatabase`, and implements
`protean.port.database.DatabasePort`

The Provider is the central coordinator. It manages connections, sessions, and
the database lifecycle. List `BaseDatabase` first in the class bases, then the
port the provider implements. `DatabasePort` declares the members every
provider has. `RawQueryDatabasePort` adds `raw()`, and a provider that declares
`DatabaseCapabilities.RAW_QUERIES` implements it. You implement the abstract
methods and the `capabilities` property listed in the table below.

The provider class also sets a `database_type` attribute to the database's
name. Protean reads it when it picks a custom repository or database model
registered for one database type (`database_type="..."`). Without it, getting a
repository fails with an `AttributeError`.

| Method | Purpose |
|--------|---------|
| `capabilities` | Property returning `DatabaseCapabilities` flags |
| `get_session()` | Return a session object for transaction management |
| `new_session()` | Return a new session, separate from the one a Unit of Work holds |
| `commit(session)` | Commit `session`; raise `ExpectedVersionError` when a version-checked write found a newer stored version |
| `rollback(session)` | Roll back `session` |
| `get_connection()` | Return the underlying database connection |
| `ping()` | Health check, return `True` if the database is reachable |
| `health()` | Return a `DatabaseHealth`; its `pool` holds connection pool counters, or `None` |
| `dao_for(entity_cls, model_cls)` | Return the adapter DAO for a given entity |
| `model_for(entity_cls, model_cls=None)` | Build a database model, or decorate `model_cls` when given |
| `clear()` | Delete all data (used in tests) |

The port gives four members a default that does nothing. Override them when
the database needs the work:

- `flush(session)` runs the session's pending writes inside its transaction,
  without committing.
- `close()` releases connections and cleans up resources.
- `create_schema()` creates tables, indices, or collections.
- `drop_schema()` drops all storage structures.

A provider that implements `RawQueryDatabasePort` also implements
`raw(query, data=None)`, which runs a native query. On a provider without its
own `raw()`, the `BaseDatabase` version raises `NotSupportedError`.

`DatabasePort` also declares the class method `get_lookups()`, which returns
the lookups the provider registers. `BaseDatabase` gets it from
`RegisterLookupMixin`, so a provider that subclasses `BaseDatabase` does not
define it. A provider that implements `DatabasePort` without `BaseDatabase`
defines it.

### 2. DAO (Data Access Object)

**Implements**: `protean.port.dao.DAOPort`

The adapter DAO runs storage operations for one entity class. Its constructor
takes `(provider, entity_cls, database_model_cls)` and sets those three
attributes and `schema_name`. `dao_for` returns an instance of it.

Every operation that touches stored rows takes a session as its first
argument. The DAO runs the operation in that session and leaves it open: it
never commits, rolls back or closes it. A store with no transactions can ignore
the session and write at once, as the Elasticsearch adapter does.

| Method | Purpose |
|--------|---------|
| `filter(session, criteria, *, offset=0, limit=10, order_by=(), with_total=True, fields=None)` | Query records, return `ResultSet`. When `with_total=False`, skip the total-count computation if it is expensive |
| `count(session, criteria)` | Count matching records via a single `COUNT`, without projecting columns or materializing entities |
| `insert(session, model)` | Insert a new record |
| `update(session, model, *, expected_version=None)` | Update an existing record. When `expected_version` is set, write only if the stored version matches |
| `update_all(session, criteria, values)` | Bulk update matching records with the `values` mapping |
| `delete(session, model)` | Delete a single record |
| `delete_all(session, criteria=None)` | Bulk delete matching records, or all records when `criteria` is `None` |
| `has_table()` | Check if the entity's table/collection exists |

Protean wraps the adapter DAO in its own `DAO` service, which repositories and
the query API use. The service opens and ends sessions, runs the save
lifecycle (`get`, `save`, `create`, `update`, `delete`), and dispatches to the
optional ports described in [Declaring Capabilities](#declaring-capabilities).

The service also provides `save_if_absent(entity, apply_hooks=True)`. It saves
the entity unless another row already holds its unique key, and returns `None`
in that case. The unique key is the fields of each `Index` declared with
`unique=True` and no `where` predicate. The outbox writes its rows through
`save_if_absent`. By default the service checks for the key with `count`, then
saves. Two writers that check at the same moment can both pass the check. If
your store has a unique index on the key, it rejects the second write with its
own error. If it has none, both rows are kept. To make the check and the write
one atomic step, the provider declares `INSERT_IF_ABSENT` and the DAO
implements `InsertIfAbsentPort`. Its `insert_if_absent(session, model)` and
`update_if_absent(session, model, *, expected_version=None)` return `False`
and write nothing when another row holds a key.

A provider that declares `RAW_QUERIES` has a DAO that implements
`RawQueryDAOPort`, whose `raw(session, query, data=None)` runs a native query.

### 3. DatabaseModel

**Extends**: `protean.core.database_model.BaseDatabaseModel` and
`protean.port.database.DatabaseModelPort`

The DatabaseModel converts between domain entities and database records.
`DatabaseModelPort` lists the three class methods Protean calls on it.
`BaseDatabaseModel` implements `to_entity` and `to_records`, so your model
must implement `from_entity` and overrides the other two only when the store
needs it:

| Method | Purpose |
|--------|---------|
| `from_entity(entity)` | Convert a domain entity to a database record |
| `to_entity(item)` | Convert a database record to a domain entity |
| `to_records(items, fields)` | Build read-only records holding only `fields`, for `QuerySet.only()` |

Subclass `BaseDatabaseModel` first and then `DatabaseModelPort`. When your
model also subclasses a database library's base class whose metaclass is not
`type` or `abc.ABCMeta` itself, Python raises a metaclass conflict `TypeError`
for the Port. A metaclass derived from `ABCMeta` conflicts too, unless it
derives from the Protocol metaclass. Leave the Port
out of the bases in that case and check the class with a typed assignment
that mypy verifies, such as
`_MODEL_PORT_CHECK: type[DatabaseModelPort] = YourModel`.

Use the `_entity_to_dict()` helper to extract attribute values from an entity
into a flat dictionary. This helper converts value objects, shadow fields, and
nested associations the same way in every adapter:

```python
# fragment
@classmethod
def from_entity(cls, entity):
    item_dict = cls._entity_to_dict(entity)
    # Perform any adapter-specific transformations
    return YourRecord(**item_dict)
```

### 4. Lookups

**Extends**: `protean.port.dao.LookupPort`

Lookups translate filter criteria into adapter-native comparison expressions.
`LookupPort` declares the lookup's `lookup_name`, its `source` and `target`,
and the `database_model_cls` it receives as a keyword-only constructor
argument. Your lookup base class sets `source`, `target` and
`database_model_cls` in its constructor and declares the method your DAO calls
to turn a lookup into a query. `LookupPort` supplies no constructor body, so a
lookup class that defines no constructor of its own builds without these
attributes.
Every adapter must register
[12 required lookups](./index.md#required-lookups), including `isnull`
(`Q(field__isnull=True/False)`), which core framework machinery such as the
outbox poll path relies on. Register them with the
`@YourDatabase.register_lookup` decorator:

```python
# fragment
from protean.port.dao import LookupPort


class YourLookup(LookupPort):
    def __init__(self, source, target, *, database_model_cls=None):
        self.source, self.target = source, target
        self.database_model_cls = database_model_cls

    def as_expression(self):
        raise NotImplementedError


@YourDatabase.register_lookup
class Exact(YourLookup):
    lookup_name = "exact"

    def as_expression(self):
        return {self.source: self.target}
```

The provider registry raises `ConfigurationError` when it loads a provider
class that does not register all 12 required lookups.

### 5. Registration Function

A `register()` function that registers the provider class with
`protean.infra.registry.databases`, the `AdapterRegistry` for database
providers. Wrap dependency imports in `try/except` so the adapter is
silently skipped if dependencies are not installed:

```python
# fragment
def register():
    """Register with Protean if dependencies are available."""
    try:
        import boto3  # Check that our dependency is installed
        from protean.infra.registry import databases

        databases.register("dynamodb", "my_package.provider.DynamoDBDatabase")
    except ImportError:
        pass  # DynamoDB SDK not installed, skip registration
```

## Example: A Delegating Provider

The provider below implements every abstract method by handing it to the
in-memory `MemoryDatabase`, and copies its lookups. Replace those calls with
calls to your database client:

```python
--8<-- "adapters/database/custom-databases/delegating_provider/__init__.py:provider"
```

Once registered, the provider is configured by its name like any other:

```python
--8<-- "adapters/database/custom-databases/delegating_provider/__init__.py:usage"
```

## Example: DynamoDB Adapter

Here is a complete example of creating a DynamoDB adapter as an external
package.

### Project Structure

```
protean-dynamodb/
├── pyproject.toml
├── src/
│   └── protean_dynamodb/
│       ├── __init__.py
│       ├── provider.py
│       ├── dao.py
│       ├── model.py
│       └── lookups.py
└── tests/
    └── conftest.py
```

### pyproject.toml

```toml
# fragment
[project]
name = "protean-dynamodb"
version = "0.1.0"
description = "DynamoDB database adapter for Protean"
requires-python = ">=3.11"
dependencies = [
    "protean>=0.15",
    "boto3>=1.28",
]

[project.entry-points."protean.databases"]
dynamodb = "protean_dynamodb:register"
```

### Registration Function

```python
# fragment
# src/protean_dynamodb/__init__.py
"""DynamoDB database adapter for Protean."""

def register():
    """Register the DynamoDB provider with Protean."""
    try:
        import boto3
        from protean.infra.registry import databases

        databases.register(
            "dynamodb",
            "protean_dynamodb.provider.DynamoDBDatabase",
        )
    except ImportError:
        pass
```

### Provider Implementation

```python
# fragment
# src/protean_dynamodb/provider.py
"""DynamoDB provider implementation."""

import boto3
from protean.port.database import (
    BaseDatabase,
    DatabaseCapabilities,
    DatabaseHealth,
    DatabasePort,
)


class DynamoDBSession:
    """Minimal session wrapper for DynamoDB.

    DynamoDB does not have transactions in the traditional sense,
    so commit/rollback/close are no-ops.
    """

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class DynamoDBDatabase(BaseDatabase, DatabasePort):
    """DynamoDB database provider for Protean."""

    database_type = "dynamodb"

    def __init__(self, name, domain, config):
        super().__init__(name, domain, config)

        self._client = boto3.resource(
            "dynamodb",
            endpoint_url=config.get("database_uri", "http://localhost:8000"),
            region_name=config.get("region", "us-east-1"),
        )

    @property
    def capabilities(self) -> DatabaseCapabilities:
        return DatabaseCapabilities.BASIC_STORAGE | DatabaseCapabilities.SCHEMA_MANAGEMENT

    def get_session(self):
        return DynamoDBSession()

    def new_session(self):
        return DynamoDBSession()

    def commit(self, session):
        session.commit()

    def rollback(self, session):
        session.rollback()

    def get_connection(self):
        return self._client

    def ping(self) -> bool:
        try:
            self._client.meta.client.describe_endpoints()
            return True
        except Exception:
            return False

    def health(self) -> DatabaseHealth:
        # boto3 manages connections internally and exposes no pool counters
        return DatabaseHealth(pool=None)

    def dao_for(self, entity_cls, model_cls):
        from protean_dynamodb.dao import DynamoDBDAO

        return DynamoDBDAO(self, entity_cls, model_cls)

    def model_for(self, entity_cls, model_cls=None):
        if model_cls is not None:
            # Enhance user-defined model with DynamoDB-specific attributes
            return model_cls

        from protean_dynamodb.model import DynamoDBModel

        # Build a model class dynamically
        return type(
            f"{entity_cls.__name__}DynamoModel",
            (DynamoDBModel,),
            {"Meta": type("Meta", (), {"part_of": entity_cls})},
        )

    def clear(self):
        # Scan and delete all items from all tables
        for table in self._client.tables.all():
            scan = table.scan()
            with table.batch_writer() as batch:
                for item in scan["Items"]:
                    batch.delete_item(Key={"id": item["id"]})

    def create_schema(self):
        # Create DynamoDB tables for registered entities
        ...

    def drop_schema(self):
        # Drop DynamoDB tables
        ...
```

### Installation and Usage

Users install your adapter package:

```bash
pip install protean-dynamodb
```

Then configure it in their domain:

```toml
# fragment
# domain.toml
[databases.default]
provider = "dynamodb"
database_uri = "http://localhost:8000"
region = "us-east-1"
```

## Session Protocol

The objects returned by `get_session()` and `new_session()` must support
three methods:

- `commit()`: Flush pending changes to the database
- `rollback()`: Discard pending changes
- `close()`: Release the connection back to the pool

Inside a Unit of Work, the `DAO` service passes the Unit of Work's session to
the adapter DAO, and the Unit of Work commits it. Outside a Unit of Work, the
service gets a session from `new_session()` for each operation. It calls the
provider's `commit(session)` when the operation succeeds and
`rollback(session)` when the operation or the commit raises an `Exception`,
then calls the session's `close()`.
Adapters without real transactions (like the DynamoDB example above) should
provide a session object with no-op implementations.

## Call Flow

Protean routes data through the adapter components as follows:

**Initialization:**

```
Domain.init()
  → databases.get(name)                    # loads your Provider class
  → Provider.__init__(name, domain, config)
  → Provider.create_schema()  # if setup_database() called
```

**Persist (within Unit of Work):**

```
Repository.add(aggregate)
  → DAO.save(aggregate)
    → DatabaseModel.from_entity(aggregate)       # your conversion
    → adapter.insert(session, model) or adapter.update(session, model)
    # UoW holds session, no commit yet

UnitOfWork.__exit__()
  → session.commit()                             # your session
  # On error: session.rollback()
```

**Persist (standalone, no Unit of Work):**

```
Repository.add(aggregate)
  → DAO.save(aggregate)
    → DatabaseModel.from_entity(aggregate)
    → Provider.new_session()
    → adapter.insert(session, model) or adapter.update(session, model)
    → Provider.commit(session)                   # Provider.rollback(session) on error
    → session.close()
```

**Retrieve:**

```
Repository.get(identifier)
  → DAO.get(identifier)
    → DAO.query.filter(id=identifier).all()
      → adapter.filter(session, criteria, offset=..., limit=..., order_by=..., with_total=..., fields=...)
        # Must return ResultSet(items, total)
      → DatabaseModel.to_entity(item)            # your conversion
```

**Count:**

```
dao.query.filter(...).count()
  → adapter.count(session, criteria)
    # Single COUNT query: no projection, no entity materialization
    # Returns an int
```

## Declaring Capabilities

Choose the `DatabaseCapabilities` flags that accurately represent what your
adapter supports. Each capability is independent of the others, so you can
combine them freely:

```python
# fragment
from protean.port.database import DatabaseCapabilities

@property
def capabilities(self) -> DatabaseCapabilities:
    # Document store with basic operations
    return DatabaseCapabilities.BASIC_STORAGE | DatabaseCapabilities.SCHEMA_MANAGEMENT

    # Full relational support
    return DatabaseCapabilities.RELATIONAL

    # Relational with native JSON and array
    return DatabaseCapabilities.RELATIONAL | DatabaseCapabilities.NATIVE_JSON | DatabaseCapabilities.NATIVE_ARRAY
```

The claim and delete flags `NATIVE_CLAIM`, `BOUNDED_DELETE` and
`FILTERED_CLAIM_CANDIDATES` are in no convenience set. A provider declares each
of them on its own, next to the set it returns.

Each of these flags goes with an operation that the provider's DAO class
implements. The DAO class subclasses the matching port from `protean.port.dao`
after `DAOPort`:

| Flag | Port | DAO method |
|------|------|------------|
| `RAW_QUERIES` | `RawQueryDAOPort` | `raw(session, query, data=None)` |
| `INSERT_IF_ABSENT` | `InsertIfAbsentPort` | `insert_if_absent(session, model)` and `update_if_absent(session, model, *, expected_version=None)` |
| `NATIVE_CLAIM` | `NativeClaimPort` | `claim(session, criteria, claim_fields, limit, order_by=(), hold_back=None)` |
| `FILTERED_CLAIM_CANDIDATES` | `ClaimCandidatesPort` | `claim_candidates(session, criteria, limit, offset, order_by, hold_back)` |
| `BOUNDED_DELETE` | `BoundedDeletePort` | `delete_top(session, criteria, limit, order_by=None)` |

```python
# fragment
from protean.port.dao import BoundedDeletePort, DAOPort


class MyDAO(DAOPort, BoundedDeletePort):
    def delete_top(self, session, criteria, limit, order_by=None) -> int:
        # Delete up to ``limit`` matching rows in one operation and return
        # how many went.
        ...
```

The `DAO` service calls the DAO method only when the provider declares the
flag. When the provider does not declare it, the service runs the portable
claim or delete, which works on every adapter. Every claim adds one to the
`_version` of each aggregate row it claims and returns the row with the new
value, so a native `claim` must do the same. A DAO class can subclass a port
whose flag its provider does not declare. When a provider declares a flag and
its DAO class does not subclass the port, the `DAO` service raises
`ConfigurationError` when it is built. A SQL provider builds it when it
registers the entity's table. Any other provider builds it on the first use of
a repository for the entity.

The portable claim and delete, and `update_all`, run inside the adapter DAO's
`claim_lock()`, which locks nothing by default. Override it when the store has
no row locks, so that two claims in one process cannot take the same row. The
memory adapter returns its provider's reentrant lock.

!!!warning
    Only declare capabilities you actually implement. The conformance test
    suite checks most declared capabilities. It does not check
    `OPTIMISTIC_LOCKING`, `CONNECTION_POOLING` or `SCHEMA_MIGRATIONS`. For
    `NATIVE_CLAIM`, `BOUNDED_DELETE` and `FILTERED_CLAIM_CANDIDATES`, it checks
    that the `DAO` service runs the DAO's own operation.

### Supporting schema migrations (optional)

The `protean db init`, `migrate`, `upgrade`, `downgrade` and `check` commands work only
with a provider that declares `SCHEMA_MIGRATIONS`. `RELATIONAL` does not include the flag, so
an adapter adds it on its own:

```python
# fragment
@property
def capabilities(self) -> DatabaseCapabilities:
    return DatabaseCapabilities.RELATIONAL | DatabaseCapabilities.SCHEMA_MIGRATIONS
```

An adapter that declares the flag also overrides `_schema_migrator(directory)`.
It returns an object that satisfies the `SchemaMigrator` protocol from
`protean.port.database`. The protocol has five methods:

- `init(domain_path)` creates the migrations folder in `directory`. It raises
  `ConfigurationError` when the folder exists and is not empty.
- `migrate(message)` writes a migration for the differences between the
  domain's tables and the database, and returns the file's path. It returns
  `None` and writes no file when there is no difference.
- `upgrade(revision="head", sql=False)` applies migrations up to `revision`.
- `downgrade(revision, sql=False)` reverts migrations down to `revision`.
- `check()` returns one line per difference between the database and the
  domain's tables, such as `add_column order.discount`, or an empty list when
  they agree. It writes nothing to the database. It raises
  `ConfigurationError` when the database is not at the latest migration or
  cannot be read.

With `sql=True`, `upgrade` and `downgrade` print the SQL and do not connect.
Each method raises `ConfigurationError` when the migration tool reports an
error.

Callers use `provider.schema_migrator(directory)`. It raises
`NotSupportedError` when the provider does not declare the flag. An adapter
that declares the flag and does not override `_schema_migrator` gets the
`BaseDatabase` version, which raises the same error. An adapter that leaves
the flag out needs neither method. The conformance suite does not check
`SCHEMA_MIGRATIONS`, so test the migrator in the adapter's own tests.

## Testing Your Adapter

### Conformance Testing

Use Protean's built-in conformance test suite to validate your adapter:

```bash
protean test test-adapter --provider=dynamodb --uri="http://localhost:8000"
```

This runs the generic test suite against your provider, automatically selecting
tests based on your declared capabilities. See
[Adapter Conformance Testing](../../testing/conformance.md) for the full
reference.

### Using the Pytest Plugin Directly

!!! warning "Deprecated since 0.19.0, removed in 0.20.0"
    `protean.integrations.pytest.adapter_conformance` and
    `protean.testing.get_generic_test_dir()` raise `RemovedInProtean020Warning`.
    See [Adapter Conformance Testing](../../testing/conformance.md#port-suites-under-testsconformance).

For more control, use the conformance pytest plugin in your own test suite:

```python
# fragment
# tests/conftest.py
pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]
```

Then run with your provider:

```bash
pytest --db-provider=dynamodb --db-uri="http://localhost:8000" \
    "$(python -c 'from protean.testing import get_generic_test_dir; print(get_generic_test_dir())')"
```

## Guidance for adapter authors

1. **Handle Connection Failures**: Implement reconnection logic, and make
   `ping()` return `True` only when the database is reachable.
2. **Declare Accurate Capabilities**: Only declare capabilities you actually
   support. Use the conformance test suite to verify.
3. **Use `_entity_to_dict()`**: Avoid duplicating entity-to-dict conversion
   logic. The helper handles value objects, shadow fields, and associations
   consistently.
4. **Register All Required Lookups**: The provider registry raises
   `ConfigurationError` when it loads a provider class that does not register
   all 12 standard lookups, or registers one as a class that does not subclass
   `LookupPort`.
5. **Provide No-Op Sessions**: If your database does not support transactions,
   provide a session with no-op `commit()`, `rollback()`, and `close()`.
6. **Test with Conformance Suite**: Run `protean test test-adapter` as part
   of your CI pipeline to catch regressions early.

## Related pages

- Review [existing adapter implementations](https://github.com/proteanhq/protean/tree/main/src/protean/adapters/database)
  for reference
- Understand [database capabilities](./index.md#database-capabilities) in
  detail
- Run the [conformance test suite](../../testing/conformance.md)
- Share your adapter with the
  [Protean community](https://github.com/proteanhq/protean/discussions)
