# Adapter Conformance Testing

Protean provides a generic test suite and tooling to verify that any database
provider correctly implements its declared capabilities. This is essential for
third-party adapter authors and useful for validating built-in adapters across
environments.

## Overview

The conformance tests check that a provider:

- Correctly implements all operations it claims to support
- Handles edge cases consistently (nulls, duplicates, concurrency)
- Works with Protean's Unit of Work, QuerySet, and repository patterns
- Passes the same tests that Protean's built-in adapters pass

The generic test suite is in `tests/adapters/repository/generic/` and covers
CRUD, filtering, ordering, transactions, raw queries, schema management,
optimistic locking, value objects, associations, and more.

## Port suites under `tests/conformance/`

The Protean repository has one folder per port under `tests/conformance/`:
`database`, `broker`, `cache` and `event_store`. The plugin for all four is
`tests/conformance/conftest.py`. pytest loads it as the folder's `conftest.py`,
so you do not register it.

Each folder holds one placeholder test until its port's suite moves in. The
database suite is still in `tests/adapters/repository/generic/`, and
`protean test test-adapter` runs it. For the other three ports,
`protean test test-adapter --port <port>` runs the port's folder; see
[CLI: `protean test test-adapter`](#cli-protean-test-test-adapter).

Each test runs against one adapter. With no options, a test runs against the
default adapter of its folder's port: `inline` for `broker`, `memory` for the
other three. A plain `pytest tests/conformance` needs no services.

The suites are tests, so the wheel that `pip install protean` fetches does
not include them. Run them from a source checkout.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | none | One of `database`, `broker`, `cache` or `event_store`. Every test in `tests/conformance/` outside that port's folder is deselected, including the tests that sit directly in `tests/conformance/`. |
| `--adapter` | `memory`, or `inline` for `broker` | The adapter's registered name, such as `postgresql` or `redis`. A name the port's registry does not know raises `ConfigurationError`, which lists the registered names. |
| `--adapter-config` | none | A JSON object merged over the adapter's built-in configuration, for example `'{"database_uri": "postgresql://localhost/test"}'`. Anything other than a JSON object stops the run with a usage error. |
| `--capability` | none | A flag name, such as `NATIVE_JSON`. pytest keeps only the tests whose `requires` or `requires_any` marker names that flag. A marker that names a composite flag, such as `BASIC_STORAGE` or <code>CRUD &#124; NATIVE_JSON</code>, names each flag in it. `none` keeps only the tests with neither marker. |

`--port` and `--capability` deselect tests only inside `tests/conformance/`.
Tests elsewhere in the same run are kept.

```bash
# Run the database folder's tests against PostgreSQL
pytest tests/conformance --port database --adapter postgresql

# Point the adapter at another database
pytest tests/conformance --port database --adapter postgresql \
    --adapter-config '{"database_uri": "postgresql://localhost:5432/other"}'

# Run only the tests that need one flag
pytest tests/conformance --port database --adapter postgresql --capability NATIVE_JSON
```

### Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `adapter_config` | function | The adapter's configuration: its built-in row with `--adapter-config` merged over it |
| `test_domain` | function, autouse | A `Domain` with the adapter under test as the port's `default` adapter |
| `adapter` | function | The adapter under test: the domain's default provider, broker or cache, or its event store |
| `run_around_tests` | function, autouse | Resets the adapter's data after each test |

A test marked `@pytest.mark.no_test_domain` gets no domain, and `test_domain`
yields `None`.

### Capability markers

A test names the capability flags it needs with a marker. The flags are the
port's capability type: `DatabaseCapabilities`, `BrokerCapabilities`,
`CacheCapabilities` or `EventStoreCapabilities`.

- `@pytest.mark.requires(Flag.A, Flag.B)` runs the test only when the adapter
  declares every flag given.
- `@pytest.mark.requires_any(Flag.A, Flag.B)` runs the test when the adapter
  declares at least one of them.

```python
# fragment
--8<-- "reference/testing/conformance/port_suite/test_capability_gates.py:test"
```

When the adapter lacks a flag, the test is skipped, and the skip reason names
the adapter and the flag:

```
SKIPPED [1] test_capability_gates.py:16: memory does not declare NATIVE_JSON
```

For a `requires_any` marker the reason names every flag, joined by `or`. An
adapter with no `capabilities` member skips every marked test with the reason
`<adapter> declares no capabilities`.

## CLI: `protean test test-adapter`

The quickest way to test an adapter is the `test-adapter` CLI command:

```bash
protean test test-adapter --provider=memory
```

`--port` picks the port whose suite runs. It defaults to `database`, which runs
the generic database suite in `tests/adapters/repository/generic/`. `broker`,
`cache` and `event_store` run the port's folder under `tests/conformance/`
with the plugin described in
[Port suites under `tests/conformance/`](#port-suites-under-testsconformance).

The suites are not in the wheel, so run the command from a Protean source
checkout. When the port's folder is missing, the command exits 1 and says that
the conformance suites need a source checkout.

### Options

| Option | Required | Description |
|--------|:--------:|-------------|
| `--provider` | Yes | The adapter's registered name for the port, such as `memory`, `postgresql` or `redis`. A name the port's registry does not know exits 1 with the registered names. |
| `--port` | No | `database` (the default), `broker`, `cache` or `event_store`. Any other value exits 1 and lists the four ports. |
| `--uri` | No | The adapter's connection URI: `database_uri` for `database` and `event_store`, `URI` for `broker` and `cache`. It replaces the same key in `--config`. |
| `--config` | No | A JSON object merged into the adapter configuration, for example `'{"TTL": 60}'`. Anything other than a JSON object exits 1. |
| `--capabilities` | No | Comma-separated capability flag names of the port, such as `EXPECTED_VERSION` (default: every flag). See below for `--port database`. |
| `--verbose` / `-v` | No | Show detailed test output |
| `--test-dir` | No | Deprecated. Path to a custom database test directory (default: built-in generic tests). `--port database` only. |

### Rows of the report

For `broker`, `cache` and `event_store`, the command runs pytest once per row
of the report. The first row, `unmarked`, runs the tests that need no flag.
Then each flag the adapter declares gets a row, in the order the port's
capability type defines them. A declared flag runs the tests whose `requires`
or `requires_any` marker names it. Each flag the adapter does not declare gets
a `SKIP (not declared)` row after all the run rows, and the command does not
run pytest for it. A declared flag with no test
yet is reported as `SKIP (no tests collected)`.

With `--capabilities`, the report has only the rows of the named flags and no
`unmarked` row. A named set, such as `BASIC`, stands for each flag in it.

For `--port database`, the rows are the marker names in
[Capability Markers](#capability-markers). A `DatabaseCapabilities` flag name
in `--capabilities` selects every row whose flags include it, so `TRANSACTIONS`
selects `transactional` and `atomic_transactions`. The marker names, such as
`basic_storage`, still work and raise `RemovedInProtean020Warning`; they are
removed in 0.20.0.

The command exits 1 when any row fails.

### Examples

```bash
# Test the memory provider (no external services needed)
protean test test-adapter --provider=memory

# Test PostgreSQL with a specific connection URI
protean test test-adapter --provider=postgresql \
    --uri="postgresql://postgres:postgres@localhost:5432/testdb"

# Test only specific capabilities
protean test test-adapter --provider=memory \
    --capabilities=CRUD,SIMULATED_TRANSACTIONS

# Test the memory event store
protean test test-adapter --port=event_store --provider=memory

# Test the Redis broker against a local server
protean test test-adapter --port=broker --provider=redis \
    --uri="redis://localhost:6379/0"

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

For the memory cache, the rows are `unmarked` and then the `CacheCapabilities`
flags:

```
Conformance Report: memory
==========================

Capability               Status     Tests
--------------------------------------------------------
unmarked                 PASS       1/1
KEY_VALUE                SKIP       (no tests collected)
TTL                      SKIP       (no tests collected)
PATTERN_MATCH            SKIP       (no tests collected)
SHARED                   SKIP       (not declared)
DURABLE                  SKIP       (not declared)
--------------------------------------------------------
Total: 1 passed, 0 failed, 0 errors, 2 capabilities skipped
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
    The `transactional` marker uses OR logic. It matches providers with either
    real transactions or simulated transactions. The `atomic_transactions`
    marker requires real database-level ACID transactions.

## Pytest Plugin

!!! warning "Deprecated since 0.19.0, removed in 0.20.0"
    `protean.integrations.pytest.adapter_conformance` raises
    `RemovedInProtean020Warning` when it is imported. It keeps working until
    0.20.0. Run `protean test test-adapter --provider <name>` from a source
    checkout instead. The database suite moves into `tests/conformance/database/`
    in a later release; see
    [Port suites under `tests/conformance/`](#port-suites-under-testsconformance).

For more control, use the conformance testing pytest plugin directly in your
test suite.

### Loading the Plugin

The conformance plugin is **not auto-registered**. Load it explicitly in your
`conftest.py`:

```python
# fragment
--8<-- "reference/testing/conformance/opt_in/conftest.py:opt_in"
```

Tests under that `conftest.py` then receive a `test_domain` configured with the
adapter under test, `memory` unless you pass `--db`:

```python
# fragment
--8<-- "reference/testing/conformance/opt_in/test_default_adapter.py:test"
```

### CLI Options

The plugin registers these pytest CLI options:

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `MEMORY` | Built-in provider key (`MEMORY`, `POSTGRESQL`, `SQLITE`, `ELASTICSEARCH`, `MSSQL`, `MYSQL`, `MARIADB`) |
| `--db-provider` | —  | Provider name for custom/external adapters (e.g. `dynamodb`) |
| `--db-uri` | —  | Database connection URI for custom adapters |
| `--db-extra` | —  | JSON string of extra provider config (e.g. `'{"pool_size": 5}'`) |

### Fixtures

The plugin provides these fixtures:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db_config` | session | Resolves provider configuration from CLI options |
| `store_config` | session | Default event store config (memory) |
| `broker_config` | session | Default broker config (inline) |
| `test_domain` | function, autouse | Creates a Domain configured with the adapter under test |
| `db` | function | Creates/drops database artifacts around each test |
| `run_around_tests` | function, autouse | Resets data after each test |

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
# fragment
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
| `test_filtering.py` | `basic_storage`, `transactional` | Filtering, lookups (incl. `isnull`, `lt`/`lte`), and `F()` column comparison |
| `test_queryset.py` | `basic_storage` | QuerySet chaining, pagination, `count()`, `only()` projection |
| `test_ordering.py` | `basic_storage` | Server-side result ordering |
| `test_bulk_operations.py` | `basic_storage` | `_update_all()`, `_delete_all()`, `_delete_top()` |
| `test_claim.py` | `transactional`, `atomic_transactions` | `_claim()` find-and-claim correctness and no-double-claim |
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

### Query API primitive coverage

The query and persistence-path primitives are gated by capability tier: an
adapter that declares a capability must pass every conformance test tagged with
it. See
[ADR-0023](../../adr/0023-query-api-conformance-contract-and-capability-tiers.md)
for the rationale.

| Primitive | Capability tier | Adapters that must pass |
|---|---|---|
| `count()` | `basic_storage` | all (including Elasticsearch) |
| `only()` projection | `basic_storage` | all |
| `isnull` lookup | `basic_storage` | all |
| `lt` / `lte` lookups | `basic_storage` | all |
| `_delete_top` bounded delete | `basic_storage` | all |
| `F()` column comparison | `transactional` | in-memory + SQL |
| `_claim` correctness | `transactional` | in-memory + SQL |
| `_claim` no-double-claim (concurrent) | `atomic_transactions` | SQL only |

`F()` and `_claim` are gated above `basic_storage` because Elasticsearch does not
support them: it raises `NotImplementedError` for `F`-bearing predicates, and its
document-versioning makes it unsuitable as a concurrent claim store. A provider
that declares only `basic_storage` (like Elasticsearch) is therefore never asked
to pass them.

## For External Adapter Authors

Follow these steps to validate your custom adapter:

### 1. Install Protean from source

The conformance suites are tests in the Protean repository, so the wheel that
`pip install protean` fetches does not include them. Install from a source
checkout:

```bash
git clone https://github.com/proteanhq/protean.git
pip install -e ./protean
```

### 2. Create `conftest.py`

!!! warning "Deprecated since 0.19.0, removed in 0.20.0"
    Steps 2 and 3 load `protean.integrations.pytest.adapter_conformance` and
    call `protean.testing.get_generic_test_dir()`. Both raise
    `RemovedInProtean020Warning` and are removed in 0.20.0.

```python
# fragment
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

## Custom Field Conformance

The same idea applies to custom fields built with
[`Custom`](../fields/custom-fields.md). Protean ships a reusable check that you
run against a `Custom` field, so you can prove your field before you depend
on it.

```python
# fragment
--8<-- "reference/testing/conformance/002.py:import"
```

`run_custom_field_conformance(field, *, valid_input, expected, invalid_input)`
takes the `Custom(...)` field under test, a raw value that should parse, the value
it should parse to, and a raw value it should reject. It builds its own in-memory
domain, declares a throwaway aggregate carrying the field, and asserts the whole
custom-field contract:

- **The outcome of each validation stage.** A required field rejects a missing
  value; an optional one resolves it to its default, or to `None`; the cast parses
  a raw value into the type and rejects one it cannot parse.
- **The `ResolvedField` reflection.** The field surfaces as a `ResolvedField` with
  the declared `required`, and its `as_dict` output is JSON-serializable.
- **A serialize, persist, reload, and event-replay round-trip.** The value saves,
  reloads equal, and replays equal from the aggregate's fact event.

`run_custom_field_conformance` raises `AssertionError` on any violation, so you
can call it directly inside a test:

```python
# fragment
--8<-- "reference/testing/conformance/002.py:test"
```

??? example "The `Color` type under test"

    ```python
    # fragment
    --8<-- "guides/domain-definition/fields/custom-fields/001.py:type"
    ```

The custom type needs a meaningful `__eq__` (the harness compares with `==`) and a
`to_dict()` that returns a value your parser accepts back, so the round-trip holds.

## Related pages

- Learn about [database capabilities](../adapters/database/index.md#database-capabilities)
- Build a [custom database adapter](../adapters/database/custom-databases.md)
- Understand the [pytest plugin](./pytest-plugin.md) for application testing
