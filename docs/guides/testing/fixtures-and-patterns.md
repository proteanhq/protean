# Fixtures and Patterns

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Reusable pytest fixtures and `conftest.py` recipes for Protean projects. When
you organize fixtures in a clear hierarchy, your tests stay focused and fast.
Shared fixtures hold the setup code, so each test holds only what it checks.

## Protean's Pytest Plugin

Protean ships with a pytest plugin. The plugin is **automatically activated**
when you install Protean, and it needs no configuration. The plugin provides:

- **`--protean-env` CLI option**: Sets `PROTEAN_ENV` before test collection
  (default: `test`). Domain instances constructed at import time then apply the
  matching `domain.toml` environment overlays.
- **Standard markers**: Registers `domain`, `application`, `integration`,
  `slow`, and `bdd` markers so `--strict-markers` accepts them without an
  error.

### `DomainFixture`

Protean also provides `DomainFixture`, a test lifecycle manager. It initializes
the domain, creates and drops the database schema, activates the domain context
for each test, and cleans up data across **all** adapters (providers, brokers,
and event store).

Import it from `protean.integrations.pytest`:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/conftest.py:import"
```

`DomainFixture` provides three methods:

| Method | What It Does |
|--------|-------------|
| `setup()` | Calls `domain.init()`, creates database schema via `domain.setup_database()`, and warns about any broker that does not answer a ping |
| `teardown()` | Drops database schema via `domain.drop_database()` |
| `domain_context()` | Context manager that activates the domain context, yields the domain, and on exit resets all data in providers, brokers, and the event store |

#### `setup()` warns about a broker that does not answer

`setup()` pings every configured broker once. For each broker that does not
answer, `setup()` emits a `UserWarning` with the broker's name and URI. The
warning shows any password as `***`:

```text
UserWarning: Broker 'default' at redis://127.0.0.1:6379/15 did not answer a
ping. Tests that publish to it will fail, and the per-test reset cannot clear it.
```

When the broker has no URI, or its URI cannot be shown without risking part of
the password, the warning
names the broker's provider instead, as in `Broker 'default' (redis provider)`.

`setup()` still returns after the warning. Tests that never touch the broker
keep running. The warning appears once, in pytest's warnings summary. Without
it, a suite whose tests never publish passes with no visible sign of a down
broker. When the per-test reset in `domain_context()` cannot clear the broker,
it logs the failure and continues. pytest shows that log line only for failing
tests.

A wrong password or a denied command also makes the ping fail, so check the
broker's credentials as well as its host and port.

To fail the run instead, turn the warning into an error, either on the command
line with `pytest -W error::UserWarning` or in your pytest configuration. Either
form makes every `UserWarning` an error, not only this one:

```toml
[tool.pytest.ini_options]
filterwarnings = ["error::UserWarning"]
```

## The Root `conftest.py`

Every Protean test suite starts with a root `conftest.py` that initializes your
application's domain. Every test in your suite runs against the domain that
this file initializes.

### Minimal conftest.py

For projects that use only in-memory adapters (the default), `tests/conftest.py`
looks like this. Here `domain` is your application's domain
(`from myapp import domain`):

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/conftest.py:conftest"
```

The examples in this section use the `User` aggregate from that domain:

??? example "The `User` aggregate under test"

    ```python
    # fragment
    --8<-- "guides/testing/myapp/models.py:user"
    ```

The session-scoped `app_fixture` initializes the domain **once** for the entire
test run. The per-test `_ctx` fixture activates the domain context for each
test. After each test, `_ctx` automatically resets all data (providers,
brokers, event store). Since your domain elements are decorated in your
application code, `domain.init()` (called inside `setup()`) discovers and wires
them automatically.

!!!tip "Use `domain.toml` for test configuration"
    Instead of setting `event_processing` and `command_processing` in code,
    you can define a `[test]` section in your `domain.toml`:

    ```toml
    [test]
    event_processing = "sync"
    command_processing = "sync"
    ```

    The pytest plugin sets `PROTEAN_ENV=test` by default. The domain then
    applies these overrides automatically when you construct it.

### Integration-Ready conftest.py

For projects that test against both in-memory and real infrastructure,
`tests/conftest.py` picks the database from an environment variable:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/integration_ready/conftest.py:conftest"
```

`DomainFixture` runs every lifecycle step for you: `setup()` calls
`domain.init()` and creates database tables for all configured providers.
`teardown()` drops them. `domain_context()` resets data in providers, brokers,
and the event store after each test.

Switch adapters from the command line:

```shell
# Default: in-memory
pytest tests/

# With PostgreSQL
TEST_DB=postgresql DATABASE_URL=postgresql://localhost/myapp_test pytest tests/

# With SQLite
TEST_DB=sqlite pytest tests/
```

Add a test that reads the provider back to confirm the switch took effect. With
that test, a typo in `TEST_DB` fails the run instead of quietly falling back to
memory:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/integration_ready/test_provider.py:provider_check"
```

## Reuse common fixture patterns

### Clean up data after each test

`DomainFixture.domain_context()` automatically resets data in all providers,
brokers, and the event store after each test. If you use the recommended
`_ctx` fixture pattern above, **no additional cleanup fixture is needed**.

If you are not using `DomainFixture` and need manual cleanup:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/manual_cleanup/conftest.py:manual_cleanup"
```

To check the cleanup, write two tests that each expect an empty store. If data
leaks between tests, the second of the two tests fails:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/manual_cleanup/test_cleanup.py:tests"
```

### Get repositories from a fixture

Provide quick access to repositories for assertions:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/test_patterns.py:repository_fixtures"
```

Use them in tests:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/test_patterns.py:repository_usage"
```

### Share BDD steps across feature files

Put steps that appear across multiple feature files in `conftest.py`.
pytest-bdd discovers the step definitions in that file automatically.

```python
# fragment
--8<-- "guides/testing/application-tests/bdd/conftest.py:shared_steps"
```

The domain is already initialized by the root `conftest.py` via
`DomainFixture`. BDD-level conftest files only need to define shared steps.

Put domain-specific shared steps in the `conftest.py` of their own directory,
such as `tests/bdd/ordering/conftest.py`:

```python
# fragment
--8<-- "guides/testing/application-tests/bdd/ordering/conftest.py:ordering_steps"
```

These steps are available to all test modules under
`tests/bdd/ordering/` without re-definition. The step hierarchy follows
pytest's `conftest.py` discovery:

```
tests/bdd/conftest.py             -> steps available everywhere
tests/bdd/ordering/conftest.py    -> steps available in ordering/ tests
tests/bdd/registration/conftest.py -> steps available in registration/ tests
```

### Override the domain configuration for one test directory

Override specific configuration for a subset of tests using a separate
`DomainFixture` in that directory's `conftest.py`:

```python
# fragment
# tests/integration/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/myapp_test",
    }
    domain.config["brokers"]["default"] = {
        "provider": "redis",
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
`tests/integration/`. The rest of the test suite continues to use in-memory
adapters. `DomainFixture` automatically creates the schema, drops it at
teardown, and cleans up data after each test.

### Reset global state between tests

If your domain uses module-level counters or caches, reset them between tests:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/test_patterns.py:global_state"
```

## Organize your test files

### Use a flat layout for smaller projects

For smaller projects, a flat layout works well:

```
tests/
├── conftest.py              # Root fixtures
├── test_book.py             # Aggregate tests
├── test_order.py            # Aggregate + entity tests
├── test_money.py            # Value object tests
└── test_fulfillment.py      # Domain service tests
```

### Organize larger projects by testing layer

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

### Choose where BDD feature files and steps go

Feature files can be organized by domain concept or by test module. The key is
consistency:

| Pattern | When to Use |
|---------|-------------|
| Feature files next to test modules | Small projects, few scenarios per concept |
| Feature files in `features/` subdirectory | Larger projects, many scenarios |
| Shared steps in parent `conftest.py` | Steps reused across multiple test modules |
| Steps in test module | Steps used only by that module's scenarios |

## Switch between in-memory and real infrastructure

To switch between in-memory and real infrastructure, Protean recommends
`--protean-env`. The option swaps all adapters at the configuration level with
**zero changes** to test code or fixtures:

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
works for both modes, no per-directory overrides needed. The "Integration-Ready
conftest" recipe above still works, but `--protean-env` is the cleaner approach
for most projects.

See the [Dual-Mode Testing](../../patterns/dual-mode-testing.md) pattern for
the complete setup, CI configuration, and multi-domain guidance.

## Run a subset of your tests

### Select tests by directory

```shell
# Unit tests only (fast)
pytest tests/unit/

# BDD application tests only
pytest tests/bdd/

# Integration tests only
pytest tests/integration/
```

### Select scenarios by Gherkin tag

```shell
# Run only scenarios tagged @ordering
pytest tests/bdd/ -m ordering

# Run smoke tests, skip slow scenarios
pytest tests/bdd/ -m "smoke and not slow"
```

### Select tests by keyword or path

```shell
# Run tests matching a pattern
pytest tests/ -k "test_order"

# Run a specific test file
pytest tests/unit/test_book.py

# Run a specific test function
pytest tests/unit/test_book.py::test_publish_changes_status
```

### Use common pytest flags

| Flag | Purpose |
|------|---------|
| `-v` | Verbose output |
| `-x` | Stop on first failure |
| `--tb=short` | Shorter tracebacks |
| `-k "pattern"` | Run tests matching pattern |
| `--lf` | Re-run only last-failed tests |
| `--pdb` | Drop into debugger on failure |

## Measure test coverage

Run your test suite with coverage to verify that your business logic meets the
100% coverage target:

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

## Freeze time in tests

Anything with a deadline, a lock expiry, or a retry backoff is awkward to test
against the real clock. The usual workaround is to sleep just under the
threshold and assert the thing has not happened yet. That workaround is a race:
on a busy CI machine, the code can take longer than the margin you left.

Every domain holds a clock on `domain.clock`. Replace the clock, and any code
reading `domain.clock` sees the time you set. Restore the original clock
afterwards, or the frozen time leaks into every test that runs next:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/test_patterns.py:frozen_clock"
```

With the clock replaced, you can write a deadline test that sets the time
directly, with no sleep to race against:

```python
# fragment
--8<-- "guides/testing/fixtures-and-patterns/minimal/test_patterns.py:deadline"
```

The default is `SystemClock`, which returns `datetime.now(UTC)`. A domain whose
clock you have not replaced behaves exactly as before. `Clock` is a `Protocol`,
so a stub does not subclass anything: a `now()` returning a timezone-aware UTC
`datetime` is the whole contract. `SystemClock` and `Clock` are both defined in
`protean.utils`.

Prefer replacing `domain.clock` to patching `datetime` at module scope. A patch
changes `datetime` only in the module you name and misses every other module.
The patch also breaks as soon as the code moves. Protean maintains the clock as
a supported point where tests can replace the time.

## Anti-Patterns to Avoid

### Don't Mock Domain Objects

```python
# fragment
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
# fragment
# BAD: Module-level state without cleanup
users_created = []

def test_one():
    users_created.append(User(name="Alice"))

def test_two():
    # users_created still has Alice from test_one!
    assert users_created == []  # fails after test_one

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
# fragment
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
