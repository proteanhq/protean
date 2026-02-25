# Adapter Conformance Testing

Protean provides a generic test suite and tooling to verify that any database
provider correctly implements its declared capabilities. This is essential for
third-party adapter authors and useful for validating built-in adapters across
environments.

## Overview

Conformance testing ensures that a provider:

- Correctly implements all operations it claims to support
- Handles edge cases consistently (nulls, duplicates, concurrency)
- Works with Protean's Unit of Work, QuerySet, and repository patterns
- Passes the same tests that Protean's built-in adapters pass

The generic test suite lives in `tests/adapters/repository/generic/` and
covers CRUD, filtering, ordering, transactions, raw queries, schema management,
optimistic locking, value objects, associations, and more.

## CLI: `protean test test-adapter`

The quickest way to test any provider is the `test-adapter` CLI command:

```bash
protean test test-adapter --provider=memory
```

### Options

| Option | Required | Description |
|--------|:--------:|-------------|
| `--provider` | Yes | Provider name (e.g. `memory`, `postgresql`, `dynamodb`) |
| `--uri` | No | Database connection URI (uses provider default if omitted) |
| `--capabilities` | No | Comma-separated list of capabilities to test (default: all declared) |
| `--verbose` / `-v` | No | Show detailed test output |
| `--test-dir` | No | Path to a custom test directory (default: built-in generic tests) |

### Examples

```bash
# Test the memory provider (no external services needed)
protean test test-adapter --provider=memory

# Test PostgreSQL with a specific connection URI
protean test test-adapter --provider=postgresql \
    --uri="postgresql://postgres:postgres@localhost:5432/testdb"

# Test only specific capabilities
protean test test-adapter --provider=memory \
    --capabilities=basic_storage,transactional

# Verbose output for debugging failures
protean test test-adapter --provider=postgresql \
    --uri="postgresql://localhost/test" -v
```

### Sample Output

```
Running conformance tests for provider 'memory' (MemoryProvider)...
Capabilities to test: basic_storage, transactional, raw_queries
Capabilities to skip: atomic_transactions, schema_management, native_json, native_array

Conformance Report: memory
==========================

Capability               Status     Tests
--------------------------------------------------------
basic_storage            PASS       42/42
transactional            PASS       12/12
raw_queries              PASS       8/8
atomic_transactions      SKIP       (not declared)
schema_management        SKIP       (not declared)
native_json              SKIP       (not declared)
native_array             SKIP       (not declared)
--------------------------------------------------------
Total: 62 passed, 0 failed, 0 errors, 4 capabilities skipped
```

## Capability Markers

Tests in the generic suite are marked with pytest markers that map to
`DatabaseCapabilities` flags. Only tests matching a provider's declared
capabilities are executed; the rest are automatically skipped.

| Pytest Marker | DatabaseCapabilities Flags |
|---------------|---------------------------|
| `basic_storage` | CRUD, FILTER, BULK_OPERATIONS, ORDERING |
| `transactional` | TRANSACTIONS or SIMULATED_TRANSACTIONS |
| `atomic_transactions` | TRANSACTIONS only (real ACID) |
| `raw_queries` | RAW_QUERIES |
| `schema_management` | SCHEMA_MANAGEMENT |
| `native_json` | NATIVE_JSON |
| `native_array` | NATIVE_ARRAY |

!!!note
    The `transactional` marker uses OR logic -- it matches providers with
    either real transactions or simulated transactions. The
    `atomic_transactions` marker requires real database-level ACID transactions.

## Pytest Plugin

For more control, use the conformance testing pytest plugin directly in your
test suite.

### Loading the Plugin

The conformance plugin is **not auto-registered**. Load it explicitly in your
`conftest.py`:

```python
# conftest.py
pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]
```

### CLI Options

The plugin registers these pytest CLI options:

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `MEMORY` | Built-in provider key (`MEMORY`, `POSTGRESQL`, `SQLITE`, `ELASTICSEARCH`, `MSSQL`) |
| `--db-provider` | -- | Provider name for custom/external adapters (e.g. `dynamodb`) |
| `--db-uri` | -- | Database connection URI for custom adapters |
| `--db-extra` | -- | JSON string of extra provider config (e.g. `'{"pool_size": 5}'`) |

### Fixtures

The plugin provides these fixtures:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db_config` | session | Resolves provider configuration from CLI options |
| `store_config` | session | Default event store config (memory) |
| `broker_config` | session | Default broker config (inline) |
| `test_domain` | autouse | Creates a Domain configured with the adapter under test |
| `db` | function | Creates/drops database artifacts around each test |
| `run_around_tests` | autouse | Resets data after each test |

### Auto-Skip Behavior

Tests are automatically skipped when the provider lacks a required capability.
No manual skip markers or conditionals are needed:

```
SKIPPED [1] Provider 'elasticsearch' (ElasticsearchProvider) lacks
required capability: raw_queries
```

### Overriding `db_config`

External adapter packages can override the `db_config` fixture for full
control:

```python
# tests/conftest.py
import pytest

pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]

@pytest.fixture(scope="session")
def db_config():
    return {
        "provider": "dynamodb",
        "database_uri": "http://localhost:8000",
        "region": "us-east-1",
    }
```

## Generic Test Suite

The generic test suite covers these areas:

| Test File | Marker | What It Tests |
|-----------|--------|---------------|
| `test_crud.py` | `basic_storage` | Create, read, update, delete single records |
| `test_filtering.py` | `basic_storage` | Query filtering with all lookup types |
| `test_queryset.py` | `basic_storage` | QuerySet chaining, pagination, Q objects |
| `test_ordering.py` | `basic_storage` | Server-side result ordering |
| `test_bulk_operations.py` | `basic_storage` | `update_all()`, `delete_all()` |
| `test_persistence.py` | `basic_storage` | End-to-end aggregate persistence |
| `test_value_objects.py` | `basic_storage` | Value object embedding and retrieval |
| `test_associations.py` | `basic_storage` | HasOne, HasMany, Reference associations |
| `test_complex_fields.py` | `basic_storage` | List, Dict, and nested field types |
| `test_optimistic_locking.py` | `basic_storage` | Version-based concurrency control |
| `test_provider.py` | `basic_storage` | Provider health checks and data reset |
| `test_provider_lifecycle.py` | `basic_storage` | Provider init, close, is_alive |
| `test_transactions.py` | `transactional` | Unit of Work commit/rollback |
| `test_atomic_transactions.py` | `atomic_transactions` | ACID transaction guarantees |
| `test_raw_queries.py` | `raw_queries` | Raw query execution |
| `test_schema_management.py` | `schema_management` | Create/drop database artifacts |
| `test_native_json.py` | `native_json` | Native JSON column support |
| `test_native_array.py` | `native_array` | Native array column support |

## For External Adapter Authors

Follow these steps to validate your custom adapter:

### 1. Install Protean

```bash
pip install protean
```

### 2. Create `conftest.py`

```python
import pytest

pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]

@pytest.fixture(scope="session")
def db_config():
    return {
        "provider": "your-provider-name",
        "database_uri": "your://connection-string",
    }
```

### 3. Run the Conformance Suite

```bash
pytest "$(python -c 'from protean.testing import get_generic_test_dir; print(get_generic_test_dir())')"
```

Or use the CLI shortcut:

```bash
protean test test-adapter --provider=your-provider-name --uri="your://connection-string"
```

### 4. Read the Report

Review which capabilities pass and which fail. Fix failures in your adapter
implementation and re-run until all declared capabilities pass.

## Next Steps

- Learn about [database capabilities](../adapters/database/index.md#database-capabilities)
- Build a [custom database adapter](../adapters/database/custom-databases.md)
- Understand the [pytest plugin](./pytest-plugin.md) for application testing
