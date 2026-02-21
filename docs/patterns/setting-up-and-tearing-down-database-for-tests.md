# Setting Up and Tearing Down Databases for Tests

## The Problem

Integration tests that touch real databases are essential for verifying that your domain model works correctly with actual persistence infrastructure. But they introduce problems that in-memory tests do not have:

- **Data leaks between tests.** A test that creates an `Order` leaves that order in the database for the next test to find. Tests that pass in isolation start failing when run together, and the failures change depending on execution order.

- **Missing schema.** The first test runs against a database that has no tables. Without explicit schema setup, every test fails with a "table not found" error -- or worse, silently passes because an exception is caught somewhere and swallowed.

- **Stale schema.** After adding a new field to an aggregate, the database tables still reflect the old schema. Tests pass locally because the developer remembered to recreate the tables, but fail in CI where the database is fresh.

- **Forgotten infrastructure cleanup.** Database tables get created and reset, but the broker still holds messages from the previous test. An event handler fires unexpectedly because a message was left over from three tests ago.

- **Slow test suites.** Creating and dropping the entire database schema before every single test is correct but slow. A test suite that takes 30 seconds with in-memory adapters takes 10 minutes against PostgreSQL because of schema overhead.

These problems share a root cause: **the lifecycle of database schema and test data are not managed separately.** Schema changes rarely (only when the domain model changes), but data changes every test. Treating them the same leads to either correctness problems (no cleanup) or performance problems (full recreation per test).

---

## The Pattern

Separate the **schema lifecycle** from the **data lifecycle**:

1. **Schema** (tables, indexes, constraints) is created once at the start of the test session and dropped once at the end. This is the expensive operation, but it only happens twice per test run.

2. **Data** (rows, messages, cached entries) is reset after every test. This is cheap -- it truncates tables and flushes in-memory stores rather than recreating them.

3. **All infrastructure** (database providers, brokers, event stores, caches) is cleaned up, not just the database. A test that publishes an event to a broker is just as capable of leaking state as one that writes a row to PostgreSQL.

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

Every Protean adapter exposes lifecycle methods designed for exactly this separation:

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

### Event Stores (`domain.event_stores`)

| Method | Purpose |
|--------|---------|
| `event_store._data_reset()` | Flush all stored events |

The in-memory adapters implement these same methods as no-ops or simple dictionary clears, so the same fixture code works regardless of which adapter is active.

---

## `DomainFixture` — The Recommended Approach

Protean provides `DomainFixture` (from `protean.integrations.pytest`) that encapsulates the entire pattern described above. It handles domain initialization, schema creation, schema teardown, and per-test data cleanup across **all** adapters automatically.

```python
from protean.integrations.pytest import DomainFixture
```

| Method | What It Does |
|--------|-------------|
| `setup()` | Calls `domain.init()` and creates database schema via `domain.setup_database()` |
| `teardown()` | Drops database schema via `domain.drop_database()` |
| `domain_context()` | Context manager that activates the domain context, yields the domain, and on exit resets all data in providers, brokers, and the event store |

This gives you the session-scoped schema lifecycle and per-test data cleanup in two fixtures:

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield
```

The recipes below show how to apply `DomainFixture` to various scenarios.

---

## Applying the Pattern

### Recipe 1: In-Memory Only

The simplest configuration. No schema management is needed because in-memory adapters have no persistent schema.

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield
```

This is sufficient for most development workflows. The domain is initialized once, and `domain_context()` resets all data between tests automatically.

---

### Recipe 2: Single Real Database

When testing against PostgreSQL, SQLite, or Elasticsearch, `DomainFixture` handles schema creation and teardown automatically.

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Create schema once for the entire test session."""
    domain.config["databases"]["default"] = {
        "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/myapp_test",
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

`DomainFixture.setup()` calls `domain.init()` and creates tables for every configured provider. `teardown()` drops them. `domain_context()` resets data after each test. Schema creation happens once; data cleanup happens hundreds of times -- but it is fast because it only truncates.

---

### Recipe 3: Switch Between In-Memory and Real Database

!!!tip "Prefer `--protean-env` for whole-suite switching"
    If you want to switch **all** adapters between in-memory and real
    infrastructure at once, Protean's `--protean-env` flag is simpler than
    manual environment variables. Define a `[memory]` overlay in `domain.toml`
    and run `pytest --protean-env memory`. See
    [Dual-Mode Testing](dual-mode-testing.md) for the full setup.

The recipe below is useful when you need to switch individual adapters
independently or control adapter selection per-directory. Use an environment
variable to control which adapter runs:

```python
# tests/conftest.py
import os

import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Configure and initialize the domain for the test session."""
    db_provider = os.environ.get("TEST_DB", "memory")

    if db_provider == "postgresql":
        domain.config["databases"]["default"] = {
            "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
            "database_uri": os.environ["DATABASE_URL"],
        }
    elif db_provider == "sqlite":
        domain.config["databases"]["default"] = {
            "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
            "database_uri": "sqlite:///test.db",
        }
    # Default: in-memory (no config override needed)

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    """Reset data after every test, regardless of adapter."""
    with app_fixture.domain_context():
        yield
```

Run from the command line:

```shell
# Fast local development (in-memory)
pytest tests/

# Integration tests against PostgreSQL
TEST_DB=postgresql DATABASE_URL=postgresql://localhost/myapp_test pytest tests/

# Integration tests against SQLite
TEST_DB=sqlite pytest tests/
```

---

### Recipe 4: Full Infrastructure (Database + Broker + Event Store)

Production systems often use a real database, a message broker, and an event store. `DomainFixture` manages all three automatically.

```python
# tests/conftest.py
import os

import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Set up all infrastructure for the test session."""
    if os.environ.get("TEST_INFRA") == "full":
        domain.config["databases"]["default"] = {
            "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
            "database_uri": os.environ["DATABASE_URL"],
        }
        domain.config["brokers"]["default"] = {
            "provider": "protean.adapters.broker.redis.RedisBroker",
            "URI": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        }
        domain.config["event_store"] = {
            "provider": "protean.adapters.event_store.message_db.MessageDBStore",
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
  DATABASE_URL=postgresql://localhost/myapp_test \
  MESSAGE_DB_URL=postgresql://localhost/message_store \
  pytest tests/
```

---

### Recipe 5: Separate Unit and Integration Fixtures

For larger projects, separate `conftest.py` files allow unit tests to run with in-memory adapters while integration tests use real infrastructure -- without environment variables.

```
tests/
├── conftest.py              # Shared: domain init with in-memory adapters
├── unit/
│   └── test_order.py        # Uses in-memory adapters from root conftest
└── integration/
    ├── conftest.py           # Override: real database config
    └── test_order_persistence.py
```

Root conftest (in-memory):

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield
```

Integration conftest (real database):

```python
# tests/integration/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    """Override root conftest for integration tests."""
    domain.config["databases"]["default"] = {
        "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/myapp_test",
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

# Everything
pytest tests/
```

---

## Common Anti-Patterns

### No Data Reset

```python
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
    orders = repo._dao.query.all()
    assert len(orders.items) == 0  # FAILS — order from previous test
```

Fix: use `DomainFixture.domain_context()` which resets all data automatically, or add a `function`-scoped `clean_data` fixture that calls `_data_reset()` on all providers and brokers.

### Recreating Schema Per Test

```python
# WRONG: Schema creation on every test — extremely slow
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

This is correct but slow. If you have 500 tests, you create and drop the entire schema 500 times. Use `DomainFixture` (which is session-scoped) or move schema operations to `scope="session"` and use `_data_reset()` per test instead.

### Forgetting Broker and Event Store Cleanup

```python
# WRONG: Only resets database, not broker
@pytest.fixture(autouse=True)
def clean_data():
    yield
    for provider in domain.providers.values():
        provider._data_reset()
    # Broker still has messages from the previous test!
```

If your test raises domain events that are published to a broker, the broker accumulates messages across tests. Use `DomainFixture.domain_context()` which resets all infrastructure automatically, or reset everything manually:

```python
# RIGHT: Reset everything
@pytest.fixture(autouse=True)
def clean_data():
    yield
    for provider in domain.providers.values():
        provider._data_reset()
    for broker in domain.brokers.values():
        broker._data_reset()
```

---

## Summary

The recommended approach is to use `DomainFixture` from `protean.integrations.pytest`, which handles all lifecycle management automatically:

| Concern | `DomainFixture` Method | Scope |
|---------|------------------------|-------|
| Domain init + schema creation | `setup()` | Once per session |
| Schema teardown | `teardown()` | Once per session |
| Data cleanup (all adapters) | `domain_context()` exit | After every test |

Under the hood, `DomainFixture` calls these adapter methods:

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
use outside of tests -- for example, to reset a development database without
dropping and recreating tables.

**The key principle: create schema once, reset data often.** This gives you the correctness of full isolation with the performance of shared infrastructure.

For fixture organization patterns, test layout conventions, and additional recipes, see [Fixtures and Patterns](../guides/testing/fixtures-and-patterns.md).

To run the same test suite against both in-memory and real adapters with zero
code changes, see [Dual-Mode Testing](dual-mode-testing.md).
