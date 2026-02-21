# Fixtures and Patterns

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


This guide covers reusable pytest fixtures and `conftest.py` recipes for
Protean projects. A well-organized fixture hierarchy keeps your tests focused,
fast, and free of boilerplate.

## Protean's Pytest Plugin

Protean ships with a pytest plugin that is **automatically activated** when
Protean is installed — no configuration required. The plugin provides:

- **`--protean-env` CLI option** — sets `PROTEAN_ENV` before test collection
  (default: `test`), so `domain.toml` environment overlays are applied when
  Domain instances are constructed at import time.
- **Standard markers** — registers `domain`, `application`, `integration`, and
  `slow` markers so `--strict-markers` doesn't complain.

### `DomainFixture`

Protean also provides `DomainFixture`, a test lifecycle manager that handles
domain initialization, database schema management, per-test context activation,
and data cleanup across **all** adapters (providers, brokers, and event store).

Import it from `protean.integrations.pytest`:

```python
from protean.integrations.pytest import DomainFixture
```

`DomainFixture` provides three methods:

| Method | What It Does |
|--------|-------------|
| `setup()` | Calls `domain.init()` and creates database schema via `domain.setup_database()` |
| `teardown()` | Drops database schema via `domain.drop_database()` |
| `domain_context()` | Context manager that activates the domain context, yields the domain, and on exit resets all data in providers, brokers, and the event store |

## The Root `conftest.py`

Every Protean test suite starts with a root `conftest.py` that initializes your
application's domain. This is the single most important file in your test
infrastructure.

### Minimal conftest.py

For projects that use only in-memory adapters (the default):

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

The session-scoped `app_fixture` initializes the domain **once** for the
entire test run. The per-test `_ctx` fixture activates the domain context
and automatically resets all data (providers, brokers, event store) after
each test. Since your domain elements are decorated in your application
code, `domain.init()` (called inside `setup()`) discovers and wires them
automatically.

!!!tip "Use `domain.toml` for test configuration"
    Instead of setting `event_processing` and `command_processing` in code,
    you can define a `[test]` section in your `domain.toml`:

    ```toml
    [test]
    event_processing = "sync"
    command_processing = "sync"
    ```

    The pytest plugin sets `PROTEAN_ENV=test` by default, so these overrides
    are applied automatically when the domain is constructed.

### Integration-Ready conftest.py

For projects that test against both in-memory and real infrastructure:

```python
# tests/conftest.py
import os

import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
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
    # Default: in-memory (no override needed)

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # calls domain.init() + creates schema
    yield fixture
    fixture.teardown()  # drops schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield
```

`DomainFixture` handles everything: `setup()` calls `domain.init()` and
creates database tables for all configured providers. `teardown()` drops
them. `domain_context()` resets data in providers, brokers, and the event
store after each test.

Switch adapters from the command line:

```shell
# Default: in-memory
pytest tests/

# With PostgreSQL
TEST_DB=postgresql DATABASE_URL=postgresql://localhost/myapp_test pytest tests/

# With SQLite
TEST_DB=sqlite pytest tests/
```

## Common Fixture Patterns

### Per-Test Data Cleanup

`DomainFixture.domain_context()` automatically resets data in all providers,
brokers, and the event store after each test. If you use the recommended
`_ctx` fixture pattern above, **no additional cleanup fixture is needed**.

If you are not using `DomainFixture` and need manual cleanup:

```python
@pytest.fixture(autouse=True)
def clean_data():
    yield
    # Reset all adapter data after each test
    for provider in domain.providers.values():
        provider._data_reset()
    for broker in domain.brokers.values():
        broker._data_reset()
```

### Repository Helper

Provide quick access to repositories for assertions:

```python
from myapp import domain
from myapp.models import User, Order


@pytest.fixture
def user_repo():
    return domain.repository_for(User)


@pytest.fixture
def order_repo():
    return domain.repository_for(Order)
```

Use them in tests:

```python
def test_user_is_persisted(user_repo):
    user_repo.add(User(name="Alice", email="alice@example.com"))
    users = user_repo._dao.query.all()
    assert len(users.items) == 1
```

### Shared BDD Steps

Steps that appear across multiple feature files belong in `conftest.py`.
pytest-bdd discovers step definitions defined there automatically.

```python
# tests/bdd/conftest.py
from pytest_bdd import given


@given("the domain is initialized")
def domain_initialized():
    """Background step — domain is already initialized by the fixture."""
    pass
```

The domain is already initialized by the root `conftest.py` via
`DomainFixture`. BDD-level conftest files only need to define shared steps.

Domain-specific shared steps go in that directory's `conftest.py`:

```python
# tests/bdd/ordering/conftest.py
from pytest_bdd import given, parsers

from myapp import domain
from myapp.models import Book, Customer, Inventory, Money


@given(
    parsers.parse('a customer "{name}"'),
    target_fixture="customer",
)
def existing_customer(name):
    customer = Customer(name=name)
    domain.repository_for(Customer).add(customer)
    return customer


@given(
    parsers.parse('a book "{title}" with {stock:d} copies in stock'),
    target_fixture="book",
)
def book_in_stock(title, stock):
    book = Book(
        title=title, author="Test Author", price=Money(amount=15.99)
    )
    domain.repository_for(Book).add(book)
    inventory = Inventory(book_id=book.id, title=title, quantity=stock)
    domain.repository_for(Inventory).add(inventory)
    return book
```

These steps are available to all test modules under
`tests/bdd/ordering/` without re-definition. The step hierarchy follows
pytest's `conftest.py` discovery:

```
tests/bdd/conftest.py             -> steps available everywhere
tests/bdd/ordering/conftest.py    -> steps available in ordering/ tests
tests/bdd/registration/conftest.py -> steps available in registration/ tests
```

### Custom Domain Configuration

Override specific configuration for a subset of tests using a separate
`DomainFixture` in that directory's `conftest.py`:

```python
# tests/integration/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["databases"]["default"] = {
        "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/myapp_test",
    }
    domain.config["brokers"]["default"] = {
        "provider": "protean.adapters.broker.redis.RedisBroker",
        "URI": "redis://localhost:6379/0",
    }
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

This overrides the root-level domain fixture for all tests under
`tests/integration/`, while the rest of the test suite continues to
use in-memory adapters. `DomainFixture` handles schema creation,
teardown, and per-test data cleanup automatically.

### Per-Test Global State Reset

If your domain uses module-level counters or caches, reset them between tests:

```python
counter = 0


@pytest.fixture(autouse=True)
def reset_counter():
    global counter
    counter = 0
    yield
```

## Test Organization Patterns

### Flat Layout

For smaller projects, a flat layout works well:

```
tests/
├── conftest.py              # Root fixtures
├── test_book.py             # Aggregate tests
├── test_order.py            # Aggregate + entity tests
├── test_money.py            # Value object tests
└── test_fulfillment.py      # Domain service tests
```

### Layered Layout

For larger projects, organize by testing layer:

```
tests/
├── conftest.py              # Root fixtures (domain setup, cleanup)
├── unit/                    # Domain model tests (always fast)
│   ├── test_book.py
│   ├── test_order.py
│   └── test_money.py
├── bdd/                     # Application tests (in-memory, BDD)
│   ├── conftest.py          # Shared BDD steps
│   ├── registration/
│   │   ├── features/
│   │   │   └── register_user.feature
│   │   ├── conftest.py      # Registration shared steps
│   │   └── test_register_user.py
│   └── ordering/
│       ├── features/
│       │   └── place_order.feature
│       ├── conftest.py      # Ordering shared steps
│       └── test_place_order.py
└── integration/             # Integration tests (real infra, BDD)
    ├── conftest.py          # Real adapter configuration
    ├── features/
    │   ├── order_flow.feature
    │   └── persistence.feature
    ├── test_order_flow.py
    └── test_persistence.py
```

### BDD Directory Conventions

Feature files can be organized by domain concept or by test module. The key is
consistency:

| Pattern | When to Use |
|---------|-------------|
| Feature files next to test modules | Small projects, few scenarios per concept |
| Feature files in `features/` subdirectory | Larger projects, many scenarios |
| Shared steps in parent `conftest.py` | Steps reused across multiple test modules |
| Steps in test module | Steps used only by that module's scenarios |

## Dual-Mode Testing

Protean's recommended approach for switching between in-memory and real
infrastructure is `--protean-env`, which swaps all adapters at the
configuration level with **zero changes** to test code or fixtures:

```shell
# Memory mode — fast, no Docker needed
pytest --protean-env memory

# Real mode — default (test), requires infrastructure
pytest
```

This works by activating different `domain.toml` environment overlays. Add a
`[memory]` section to your `domain.toml` that overrides all adapter providers
to their in-memory equivalents:

```toml
# In your domain.toml
[memory]
testing = true
event_processing = "sync"

[memory.databases.default]
provider = "memory"

[memory.event_store]
provider = "memory"

[memory.brokers.default]
provider = "inline"
```

Because `--protean-env` applies before test collection, a single `conftest.py`
works for both modes -- no per-directory overrides needed. The "Integration-Ready
conftest" recipe above still works, but `--protean-env` is the cleaner approach
for most projects.

See the [Dual-Mode Testing](../../patterns/dual-mode-testing.md) pattern for
the complete setup, CI configuration, and multi-domain guidance.

## Running Tests Selectively

### By Directory

```shell
# Unit tests only (fast)
pytest tests/unit/

# BDD application tests only
pytest tests/bdd/

# Integration tests only
pytest tests/integration/
```

### By Gherkin Tag

```shell
# Run only scenarios tagged @ordering
pytest tests/bdd/ -m ordering

# Run smoke tests, skip slow scenarios
pytest tests/bdd/ -m "smoke and not slow"
```

### By Keyword

```shell
# Run tests matching a pattern
pytest tests/ -k "test_order"

# Run a specific test file
pytest tests/unit/test_book.py

# Run a specific test function
pytest tests/unit/test_book.py::test_publish_changes_status
```

### Useful pytest Flags

| Flag | Purpose |
|------|---------|
| `-v` | Verbose output |
| `-x` | Stop on first failure |
| `--tb=short` | Shorter tracebacks |
| `-k "pattern"` | Run tests matching pattern |
| `--lf` | Re-run only last-failed tests |
| `--pdb` | Drop into debugger on failure |

## Coverage Reporting

Run your test suite with coverage to verify you're hitting the 100% target
on business logic:

```shell
# Run all tests with coverage
pytest --cov=myapp --cov-report=html tests/

# Run with a minimum coverage threshold
pytest --cov=myapp --cov-fail-under=100 tests/
```

Exclude setup files from coverage in your `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["myapp"]
omit = ["myapp/__init__.py", "myapp/config.py"]
```

## Anti-Patterns to Avoid

### Don't Mock Domain Objects

```python
# BAD: Mocking hides real behavior
user = Mock(spec=User)
user.status = "ACTIVE"

# GOOD: Use real objects
user = User(name="John", email="john@example.com")
user.activate()
assert user.status == "ACTIVE"
```

### Don't Share State Between Tests

```python
# BAD: Module-level state without cleanup
users_created = []

def test_one():
    users_created.append(User(name="Alice"))

def test_two():
    # users_created still has Alice from test_one!

# GOOD: Use fixtures for cleanup
@pytest.fixture(autouse=True)
def reset_state():
    users_created.clear()
    yield
```

### Don't Test Framework Mechanics

Protean guarantees that fields, value objects, and event dispatch work
correctly. Don't waste tests on behavior the framework already ensures:

```python
# BAD: Testing that required=True works
def test_string_required():
    with pytest.raises(ValidationError):
        User()  # name is required -- Protean already guarantees this

# BAD: Testing value object immutability
def test_money_is_immutable():
    m = Money(amount=10.0)
    with pytest.raises(InvalidOperationError):
        m.amount = 20.0  # Protean guarantees immutability

# GOOD: Test YOUR business rules and custom logic
def test_user_cannot_activate_without_email():
    user = User(name="John")
    with pytest.raises(ValidationError) as exc:
        user.activate()
    assert "email required for activation" in str(exc.value.messages)
```
