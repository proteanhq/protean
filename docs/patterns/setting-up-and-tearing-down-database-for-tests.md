# Setting Up and Tearing Down Databases for Tests

## The Problem

Integration tests against real databases check your domain model with actual
persistence infrastructure. You need them to know the model works with that
infrastructure. But they introduce problems that in-memory tests do not have:

- **Data leaks between tests**: A test that creates an `Order` leaves that
  order in the database for the next test to find. Tests that pass alone start
  to fail when you run them together. Which tests fail changes with the
  execution order.

- **Missing schema**: The first test runs against a database that has no
  tables. Without explicit schema setup, a test fails with a "table not found"
  error, or worse, passes silently because some code catches the exception and
  swallows it.

- **Stale schema**: After adding a new field to an aggregate, the database
  tables still reflect the old schema. Tests pass locally after the developer
  recreates the tables by hand. The same tests fail in CI, where the database
  is fresh.

- **Forgotten infrastructure cleanup**: Database tables get created and reset, but the broker still holds messages from the previous test. An event handler fires unexpectedly because a message was left over from three tests ago.

- **Slow test suites**: If your fixtures create and drop the entire database
  schema before every test, the tests are correct but slow. With in-memory
  adapters, a test suite might run in 30 seconds. Against PostgreSQL, the
  schema work stretches the same suite to 10 minutes.

These problems share a root cause: **the test setup manages the database schema
and the test data on one lifecycle.** Schema changes rarely (only when the
domain model changes), but data changes in every test. Treating them the same
leads to either correctness problems (no cleanup) or performance problems (full
recreation per test).

---

## The Pattern

Separate the **schema lifecycle** from the **data lifecycle**:

1. **Schema** (tables, indexes, constraints) is created once at the start of the test session and dropped once at the end. This is the expensive operation, but it only happens twice per test run.

2. **Data** (rows, messages, events) is reset after every test. This
   is cheap. The reset truncates tables and flushes in-memory stores, and
   leaves them in place.

3. **All infrastructure** (database providers, brokers, event stores) is cleaned up, not just the database. `DomainFixture` does not reset caches. A test that publishes an event to a broker is just as capable of leaking state as one that writes a row to PostgreSQL.

```
Session start:   create schema for all providers
                      ↓
Test 1:          run test → reset data in all providers, brokers, event stores
                      ↓
Test 2:          run test → reset data in all providers, brokers, event stores
                      ↓
...
                      ↓
Session end:     drop schema for all providers
```

---

## How Protean Supports This

Every Protean adapter exposes lifecycle methods that keep the schema lifecycle
apart from the data lifecycle:

### Database Providers (`domain.providers`)

| Method | Purpose |
|--------|---------|
| `provider._create_database_artifacts()` | Create tables, indexes, and constraints for all registered aggregates, entities, and projections |
| `provider._drop_database_artifacts()` | Drop all tables and schema objects |
| `provider._data_reset()` | Truncate all tables, preserving schema |

### Brokers (`domain.brokers`)

| Method | Purpose |
|--------|---------|
| `broker._data_reset()` | Flush all messages and consumer group state |

### Event Store (`domain.event_store`)

| Method | Purpose |
|--------|---------|
| `domain.event_store.store._data_reset()` | Flush all stored events |

The in-memory adapters implement the lifecycle methods in the tables above as
no-ops or dictionary clears. Your fixture code therefore works with any active
adapter.

---

## `DomainFixture`: The Recommended Approach

Protean provides `DomainFixture` (from `protean.integrations.pytest`) that
encapsulates the entire pattern described above. `DomainFixture` initializes
the domain, creates the schema, drops the schema, and cleans up data after each
test across **all** adapters automatically.

```python
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/in_memory/conftest.py:import"
```

| Method | What It Does |
|--------|-------------|
| `setup()` | Calls `domain.init()` and creates database schema via `domain.setup_database()` |
| `teardown()` | Drops database schema via `domain.drop_database()` |
| `domain_context()` | Context manager that activates the domain context, yields the domain, and on exit resets all data in providers, brokers, and the event store |

With `DomainFixture`, you get the session-scoped schema lifecycle and per-test
data cleanup from two fixtures in `tests/conftest.py`:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/in_memory/conftest.py:conftest"
```

The recipes below show how to apply `DomainFixture` to various scenarios.

---

## Applying the Pattern

### Recipe 1: In-Memory Only

The simplest configuration. No schema management is needed because in-memory adapters have no persistent schema. In `tests/conftest.py`:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/in_memory/conftest.py:conftest"
```

This is sufficient for most development workflows. The fixture initializes the
domain once. `domain_context()` resets all data between tests automatically.

The two tests below each expect an empty store, so they show the reset from
`domain_context()`. If the first test's order is still in the store, the second
test fails:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/in_memory/test_orders.py:tests"
```

---

### Recipe 2: Single Real Database

When you test against PostgreSQL, SQLite, or Elasticsearch, `DomainFixture`
creates and drops the schema automatically. In `tests/conftest.py`:

```python
# fragment
import pytest

from protean.integrations.pytest import DomainFixture

from orderdesk import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Create schema once for the entire test session."""
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/orderdesk_test",
    }
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    """Reset data after every test."""
    with app_fixture.domain_context():  # resets all data on exit
        yield
```

`DomainFixture.setup()` calls `domain.init()` and creates tables for every
configured provider. `teardown()` drops them. `domain_context()` resets data
after each test. The fixture creates the schema once per session. It cleans up
data hundreds of times, and each cleanup is fast because it only truncates
tables.

---

### Recipe 3: Switch Between In-Memory and Real Database

!!! tip "Prefer `--protean-env` for whole-suite switching"
    If you want to switch **all** adapters between in-memory and real
    infrastructure at once, Protean's `--protean-env` flag is simpler than
    manual environment variables. Define a `[memory]` overlay in `domain.toml`.
    Then run `pytest --protean-env memory`. See [Dual-Mode
    Testing](dual-mode-testing.md) for the full setup.

The recipe below is useful when you need to switch individual adapters
independently or control adapter selection per-directory. Use an environment
variable to control which adapter runs, in `tests/conftest.py`:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/env_switch/conftest.py:conftest"
```

A test can read which provider the run uses. With `TEST_DB=sqlite`, the test
below proves the run reached SQLite:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/env_switch/test_orders.py:tests"
```

Run from the command line:

```shell
# Fast local development (in-memory)
pytest tests/

# Integration tests against PostgreSQL
TEST_DB=postgresql DATABASE_URL=postgresql://localhost/orderdesk_test pytest tests/

# Integration tests against SQLite
TEST_DB=sqlite pytest tests/
```

---

### Recipe 4: Full Infrastructure (Database + Broker + Event Store)

Production systems often use a real database, a message broker, and an event
store. `DomainFixture` sets up and resets all three automatically. In
`tests/conftest.py`:

```python
# fragment
import os

import pytest

from protean.integrations.pytest import DomainFixture

from orderdesk import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Set up all infrastructure for the test session."""
    if os.environ.get("TEST_INFRA") == "full":
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": os.environ["DATABASE_URL"],
        }
        domain.config["brokers"]["default"] = {
            "provider": "redis",
            "URI": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        }
        domain.config["event_store"] = {
            "provider": "message_db",
            "database_uri": os.environ["MESSAGE_DB_URL"],
        }

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    """Reset data across all infrastructure after every test."""
    with app_fixture.domain_context():  # resets providers, brokers, event store
        yield
```

```shell
# In-memory only
pytest tests/

# Full infrastructure
TEST_INFRA=full \
  DATABASE_URL=postgresql://localhost/orderdesk_test \
  MESSAGE_DB_URL=postgresql://localhost/message_store \
  pytest tests/
```

---

### Recipe 5: Separate Unit and Integration Fixtures

For larger projects, separate `conftest.py` files allow unit tests to run with in-memory
adapters while integration tests use real infrastructure, without environment
variables.

```
tests/
├── conftest.py              # Shared: domain init with in-memory adapters
├── unit/
│   └── test_order.py        # Uses in-memory adapters from root conftest
└── integration/
    ├── conftest.py           # Override: real database config
    └── test_order_persistence.py
```

Root conftest (in-memory), in `tests/conftest.py`:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/in_memory/conftest.py:conftest"
```

Integration conftest (real database), in `tests/integration/conftest.py`:

```python
# fragment
import pytest

from protean.integrations.pytest import DomainFixture

from orderdesk import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Override root conftest for integration tests."""
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/orderdesk_test",
    }
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    """Reset data after each integration test."""
    with app_fixture.domain_context():  # resets providers, brokers, event store
        yield
```

Run selectively:

```shell
# Fast unit tests only
pytest tests/unit/

# Integration tests only (requires running services)
pytest tests/integration/
```

Run the two folders in separate pytest runs. Both conftests change the same
`domain` object. In a single `pytest tests/` run, the unit tests that run after
the integration tests keep the integration fixture's database setting.

---

## Common Anti-Patterns

### No Data Reset

```python
# fragment
# WRONG: No cleanup between tests
@pytest.fixture(autouse=True, scope="session")
def setup_database():
    domain.init()
    with domain.domain_context():
        for provider in domain.providers.values():
            provider._create_database_artifacts()
        yield
        for provider in domain.providers.values():
            provider._drop_database_artifacts()

# Tests leak data into each other:
def test_create_order():
    repo = domain.repository_for(Order)
    repo.add(Order(customer_id="c1", total=100))

def test_no_orders_exist():
    repo = domain.repository_for(Order)
    orders = repo.query.all()
    assert len(orders.items) == 0  # FAILS: order from previous test
```

Fix: use `DomainFixture.domain_context()`, which resets all data automatically.
Or add a `function`-scoped `clean_data` fixture that calls `_data_reset()` on
all providers, all brokers and the event store.

### Recreating Schema Per Test

```python
# fragment
# WRONG: Schema creation on every test is extremely slow
@pytest.fixture(autouse=True)
def setup_database():
    domain.init()
    with domain.domain_context():
        for provider in domain.providers.values():
            provider._create_database_artifacts()
        yield
        for provider in domain.providers.values():
            provider._drop_database_artifacts()
```

A fixture that recreates the schema per test is correct but slow. If you have
500 tests, you create and drop the entire schema 500 times. Use `DomainFixture`
(which is session-scoped) or move schema operations to `scope="session"` and
use `_data_reset()` per test instead.

### Forgetting Broker and Event Store Cleanup

```python
# fragment
# WRONG: Only resets database, not broker
@pytest.fixture(autouse=True)
def clean_data():
    yield
    for provider in domain.providers.values():
        provider._data_reset()
    # Broker still has messages from the previous test!
```

If your test raises domain events that are published to a broker, the broker accumulates messages across tests. Use `DomainFixture.domain_context()` which resets all infrastructure automatically, or reset every provider, broker and the event store yourself:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/manual_cleanup/conftest.py:clean_data"
```

Each pair of tests below expects an empty database, broker stream and event
store at the start. If any store kept data, the second test of the pair fails.
With the in-memory adapters, the provider reset also empties the event store,
because the memory event store keeps its messages in the memory provider. The
last line of `clean_data` matters for a separate event store such as MessageDB:

```python
# fragment
--8<-- "patterns/setting-up-and-tearing-down-database-for-tests/manual_cleanup/test_cleanup.py:tests"
```

---

## Summary

Use `DomainFixture` from `protean.integrations.pytest`. `DomainFixture` creates
the schema, drops it, and resets data automatically:

| Concern | `DomainFixture` Method | Scope |
|---------|------------------------|-------|
| Domain init + schema creation | `setup()` | Once per session |
| Schema teardown | `teardown()` | Once per session |
| Data cleanup (all adapters) | `domain_context()` exit | After every test |

`DomainFixture` calls the adapter methods in the table below:

| Concern | Adapter Method | Scope |
|---------|----------|-------|
| Schema creation | `domain.setup_database()` | Once per session |
| Schema teardown | `domain.drop_database()` | Once per session |
| Data truncation | `domain.truncate_database()` | On demand |
| Data cleanup (database) | `provider._data_reset()` | After every test |
| Data cleanup (broker) | `broker._data_reset()` | After every test |
| Data cleanup (event store) | `event_store.store._data_reset()` | After every test |

`domain.truncate_database()` deletes all rows from every table while preserving
the schema. It is also available as a CLI command (`protean db truncate`) for
use outside of tests, for example, to reset a development database without
dropping and recreating tables.

**The key principle: create schema once, reset data often.** With this split,
your tests stay as isolated as with a fresh database per test and run as fast
as with a shared one.

For fixture organization patterns, test layout conventions, and additional recipes, see [Fixtures and Patterns](../guides/testing/fixtures-and-patterns.md).

To run the same test suite against both in-memory and real adapters with zero
code changes, see [Dual-Mode Testing](dual-mode-testing.md).
