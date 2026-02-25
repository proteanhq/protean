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

**Extends**: `protean.port.provider.BaseProvider`

The Provider is the central coordinator. It manages connections, sessions, and
the database lifecycle. You implement 12 abstract methods plus a `capabilities`
property.

| Method | Purpose |
|--------|---------|
| `capabilities` | Property returning `DatabaseCapabilities` flags |
| `get_session()` | Return a session object for transaction management |
| `get_connection()` | Return the underlying database connection |
| `is_alive()` | Health check -- return `True` if the database is reachable |
| `close()` | Release connections and clean up resources |
| `get_dao(entity_cls, model_cls)` | Return a DAO for a given entity |
| `construct_database_model_class(entity_cls)` | Auto-generate a database model |
| `decorate_database_model_class(entity_cls, model_cls)` | Enhance a user-defined model |
| `_raw(query, data)` | Execute a raw/native query |
| `_data_reset()` | Flush all data (used in tests) |
| `_create_database_artifacts()` | Create tables, indices, or collections |
| `_drop_database_artifacts()` | Drop all storage structures |

### 2. DAO (Data Access Object)

**Extends**: `protean.port.dao.BaseDAO`

The DAO encapsulates data access operations. `BaseDAO` provides lifecycle
wrappers (`get`, `save`, `create`, `update`, `delete`) -- you implement the
underscored internals:

| Method | Purpose |
|--------|---------|
| `_filter(criteria, offset, limit, order_by)` | Query records, return `ResultSet` |
| `_create(model_obj)` | Insert a new record |
| `_update(model_obj)` | Update an existing record |
| `_update_all(criteria, values)` | Bulk update matching records |
| `_delete(model_obj)` | Delete a single record |
| `_delete_all(criteria)` | Bulk delete matching records |
| `_raw(query, data)` | Execute a raw query |
| `has_table()` | Check if the entity's table/collection exists |

### 3. DatabaseModel

**Extends**: `protean.core.database_model.BaseDatabaseModel`

The DatabaseModel converts between domain entities and database records. Two
abstract methods:

| Method | Purpose |
|--------|---------|
| `from_entity(entity)` | Convert a domain entity to a database record |
| `to_entity(item)` | Convert a database record to a domain entity |

Use the `_entity_to_dict()` helper to extract attribute values from an entity
into a flat dictionary. This helper handles value objects, shadow fields, and
nested associations consistently across all adapters:

```python
@classmethod
def from_entity(cls, entity):
    item_dict = cls._entity_to_dict(entity)
    # Perform any adapter-specific transformations
    return YourRecord(**item_dict)
```

### 4. Lookups

**Extends**: `protean.port.dao.BaseLookup`

Lookups translate filter criteria into adapter-native comparison expressions.
Every adapter must register
[11 required lookups](./index.md#required-lookups). Register them with the
`@YourProvider.register_lookup` decorator:

```python
@YourProvider.register_lookup
class Exact(BaseLookup):
    lookup_name = "exact"

    def as_expression(self):
        return self.process_source() == self.process_target()
```

### 5. Registration Function

A `register()` function that registers the provider class with Protean's
`ProviderRegistry`. Wrap dependency imports in `try/except` so the adapter is
silently skipped if dependencies are not installed:

```python
def register():
    """Register with Protean if dependencies are available."""
    try:
        import boto3  # Check that our dependency is installed
        from protean.port.provider import registry

        registry.register("dynamodb", "my_package.provider.DynamoDBProvider")
    except ImportError:
        pass  # DynamoDB SDK not installed, skip registration
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
[tool.poetry]
name = "protean-dynamodb"
version = "0.1.0"
description = "DynamoDB database adapter for Protean"

[tool.poetry.dependencies]
python = "^3.11"
protean = "^0.15"
boto3 = "^1.28"

[tool.poetry.plugins."protean.providers"]
dynamodb = "protean_dynamodb:register"
```

### Registration Function

```python
# src/protean_dynamodb/__init__.py
"""DynamoDB database adapter for Protean."""

def register():
    """Register the DynamoDB provider with Protean."""
    try:
        import boto3
        from protean.port.provider import registry

        registry.register(
            "dynamodb",
            "protean_dynamodb.provider.DynamoDBProvider",
        )
    except ImportError:
        pass
```

### Provider Implementation

```python
# src/protean_dynamodb/provider.py
"""DynamoDB provider implementation."""

from typing import Any

import boto3
from protean.port.provider import BaseProvider, DatabaseCapabilities


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


class DynamoDBProvider(BaseProvider):
    """DynamoDB database provider for Protean."""

    def __init__(self, name, domain, conn_info: dict):
        super().__init__(name, domain, conn_info)

        self._client = boto3.resource(
            "dynamodb",
            endpoint_url=conn_info.get("database_uri", "http://localhost:8000"),
            region_name=conn_info.get("region", "us-east-1"),
        )

    @property
    def capabilities(self) -> DatabaseCapabilities:
        return DatabaseCapabilities.BASIC_STORAGE | DatabaseCapabilities.SCHEMA_MANAGEMENT

    def get_session(self):
        return DynamoDBSession()

    def get_connection(self):
        return self._client

    def is_alive(self) -> bool:
        try:
            self._client.meta.client.describe_endpoints()
            return True
        except Exception:
            return False

    def close(self):
        pass  # boto3 manages connections internally

    def get_dao(self, entity_cls, database_model_cls):
        from protean_dynamodb.dao import DynamoDBDAO

        return DynamoDBDAO(self.domain, self, entity_cls, database_model_cls)

    def construct_database_model_class(self, entity_cls):
        from protean_dynamodb.model import DynamoDBModel

        # Build a model class dynamically
        return type(
            f"{entity_cls.__name__}DynamoModel",
            (DynamoDBModel,),
            {"Meta": type("Meta", (), {"part_of": entity_cls})},
        )

    def decorate_database_model_class(self, entity_cls, database_model_cls):
        # Enhance user-defined model with DynamoDB-specific attributes
        return database_model_cls

    def _raw(self, query: Any, data: Any = None):
        # Not supported -- capability not declared
        raise NotImplementedError

    def _data_reset(self):
        # Scan and delete all items from all tables
        for table in self._client.tables.all():
            scan = table.scan()
            with table.batch_writer() as batch:
                for item in scan["Items"]:
                    batch.delete_item(Key={"id": item["id"]})

    def _create_database_artifacts(self):
        # Create DynamoDB tables for registered entities
        ...

    def _drop_database_artifacts(self):
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
# domain.toml
[databases.default]
provider = "dynamodb"
database_uri = "http://localhost:8000"
region = "us-east-1"
```

## Session Protocol

The objects returned by `get_session()` and `get_connection()` must support
three methods:

- `commit()` -- Flush pending changes to the database
- `rollback()` -- Discard pending changes
- `close()` -- Release the connection back to the pool

`BaseDAO._commit_if_standalone()` calls these methods when operating outside a
Unit of Work. Adapters without real transactions (like the DynamoDB example
above) should provide a session object with no-op implementations.

## Call Flow

Understanding how Protean routes data through the adapter components:

**Initialization:**

```
Domain.init()
  → ProviderRegistry.get(name)             # loads your Provider class
  → Provider.__init__(name, domain, conn_info)
  → Provider._create_database_artifacts()  # if setup_database() called
```

**Persist (within Unit of Work):**

```
Repository.add(aggregate)
  → DAO.save(aggregate)
    → DatabaseModel.from_entity(aggregate)       # your conversion
    → DAO._create(model_obj) or DAO._update(model_obj)
    # UoW holds session — no commit yet

UnitOfWork.__exit__()
  → session.commit()                             # your session
  # On error: session.rollback()
```

**Persist (standalone, no Unit of Work):**

```
Repository.add(aggregate)
  → DAO.save(aggregate)
    → DatabaseModel.from_entity(aggregate)
    → DAO._create(model_obj) or DAO._update(model_obj)
    → DAO._commit_if_standalone(conn)
      → conn.commit() / conn.rollback() / conn.close()
```

**Retrieve:**

```
Repository.get(identifier)
  → DAO.get(identifier)
    → DAO.query.filter(id=identifier).all()
      → DAO._filter(criteria, offset, limit, order_by)
        # Must return ResultSet(items, total)
      → DatabaseModel.to_entity(item)            # your conversion
```

## Declaring Capabilities

Choose the `DatabaseCapabilities` flags that accurately represent what your
adapter supports. Capabilities are orthogonal -- combine them freely:

```python
from protean.port.provider import DatabaseCapabilities

@property
def capabilities(self) -> DatabaseCapabilities:
    # Document store with basic operations
    return DatabaseCapabilities.BASIC_STORAGE | DatabaseCapabilities.SCHEMA_MANAGEMENT

    # Full relational support
    return DatabaseCapabilities.RELATIONAL

    # Relational with native JSON and array
    return DatabaseCapabilities.RELATIONAL | DatabaseCapabilities.NATIVE_JSON | DatabaseCapabilities.NATIVE_ARRAY
```

!!!warning
    Only declare capabilities you actually implement. The conformance test
    suite will verify that your adapter correctly supports every declared
    capability.

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

For more control, use the conformance pytest plugin in your own test suite:

```python
# tests/conftest.py
pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]
```

Then run with your provider:

```bash
pytest --db-provider=dynamodb --db-uri="http://localhost:8000" \
    "$(python -c 'from protean.testing import get_generic_test_dir; print(get_generic_test_dir())')"
```

## Best Practices

1. **Handle Connection Failures** -- Implement reconnection logic and return
   meaningful results from `is_alive()`.
2. **Declare Accurate Capabilities** -- Only declare capabilities you actually
   support. Use the conformance test suite to verify.
3. **Use `_entity_to_dict()`** -- Avoid duplicating entity-to-dict conversion
   logic. The helper handles value objects, shadow fields, and associations
   consistently.
4. **Register All Required Lookups** -- Protean validates that all 11 standard
   lookups are registered. Missing lookups produce warnings at domain init.
5. **Provide No-Op Sessions** -- If your database does not support transactions,
   provide a session with no-op `commit()`, `rollback()`, and `close()`.
6. **Test with Conformance Suite** -- Run `protean test test-adapter` as part
   of your CI pipeline to catch regressions early.

## Next Steps

- Review [existing adapter implementations](https://github.com/proteanhq/protean/tree/main/src/protean/adapters/repository)
  for reference
- Understand [database capabilities](./index.md#database-capabilities) in
  detail
- Run the [conformance test suite](../../testing/conformance.md)
- Share your adapter with the
  [Protean community](https://github.com/proteanhq/protean/discussions)
