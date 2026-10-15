# Integration Tests

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Integration tests verify that your application works correctly with real
infrastructure, databases, message brokers, event stores, and caches. They
exercise the same code paths as production, giving you confidence that your
domain logic persists and communicates correctly through real adapters.

Like [application tests](./application-tests.md), we recommend using
**pytest-bdd** for integration tests. The BDD structure works just as well
here. The only difference is the domain is configured with real infrastructure
instead of in-memory adapters.

Integration tests are written the same way as
[application tests](./application-tests.md), with feature files and step
definitions, but they swap in real adapters (PostgreSQL, Redis, etc.) via
configuration overrides. Use pytest markers to
keep them separate from your fast in-memory suite.

## Configuring for Real Infrastructure

The key difference from application tests is the domain configuration. Override
your database, broker, or event store settings in a dedicated `conftest.py`
and use `DomainFixture` to manage the lifecycle:

```python
# fragment
# tests/integration/conftest.py
import pytest
from pytest_bdd import given

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
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield


@given("the domain is initialized")
def domain_initialized():
    pass
```

!!!note
    `DomainFixture.setup()` calls `domain.init()` and creates database
    tables for all configured providers. `teardown()` drops them.
    `domain_context()` resets all data (providers, brokers, event store)
    after each test. The same application code and domain elements are
    used, only the infrastructure changes.

## Using Server Test Mode

For integration tests that exercise async message flows (event handlers,
projectors, process managers), use the server's **test mode**. It processes
all available messages and cascading events, then exits.

The examples in this section test the domain below. Placing an order raises
`OrderPlaced`. An event handler reserves stock and raises `InventoryReserved`,
and a second handler marks the order shipped. The fixtures set both processing
modes to `"async"`, so these handlers run only when the engine runs:

??? example "The domain and fixtures under test"

    ```python
    # fragment
    --8<-- "guides/testing/integration-tests/fulfillment/__init__.py:domain"
    ```

    ```python
    # fragment
    --8<-- "guides/testing/integration-tests/conftest.py:conftest"
    ```

    The tests read an order back with a small helper in the test module:

    ```python
    # fragment
    --8<-- "guides/testing/integration-tests/001.py:get_order"
    ```

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:engine_test_mode"
```

Test mode handles cascading events automatically. If processing one event
raises another, the engine continues until all chains are complete:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:cascade"
```

You can also invoke test mode from the CLI:

```bash
protean server --domain=my_domain --test-mode
```

See [Run the Server](../server/index.md#test-mode) for CLI details.

## Driving flows with `process_and_wait`

The `Engine(domain, test_mode=True).run()` calls above are the low-level
primitive. For most tests `protean.testing` provides higher-level helpers that
make the **same test body work in both synchronous and asynchronous processing
modes**, and hand you the events and errors without reaching into outbox rows or
event-store streams.

`process_and_wait(command, domain)` processes a command through its full runtime
path (`handler → aggregate → UoW commit → outbox → engine → subscription →
projector`) and waits for the effects to settle. In sync mode the chain runs
inline; in async mode it drains a bounded test-mode engine before returning. It
returns a `ProcessResult`:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:process_and_wait"
```

A `ProcessResult` exposes exactly what an integration test asserts on:

- `result`: The handler's return value (sync) or the enqueued command's store position (async).
- `events`: An `EventLog` of every event raised in the command's correlation chain.
- `error` / `succeeded` / `failed`: the synchronous or submission-time error (an unregistered command, an expired deadline, a duplicate key, an enrichment `ValidationError`). Asynchronous *handler* failures happen after the command is enqueued, are absorbed by the engine (retries or DLQ), and are not surfaced here.

### Asserting on events with `EventLog`

`outcome.events` is an `EventLog` with Pythonic access by type or index:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:event_log"
```

### Waiting for a condition with `drain`

When you drive the flow yourself, or need to wait for a later cascade to settle,
`drain` runs the test-mode engine until a predicate is satisfied. It replaces
the copy-pasted `for _ in range(N): Engine(...).run()` loop:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:drain"
```

`drain` is bounded by `max_cycles` (default 5) so a never-satisfied `until`
cannot hang the test. If the budget is exhausted before the condition settles,
`drain` returns and emits a `UserWarning`, so an unmet expectation is never
silently swallowed. An engine pass stops once nothing is left to process and
takes at most about a second, so raise `max_cycles` only for flows that
genuinely need more passes.

## Full-Flow Feature Files

Integration tests exercise complete flows from command to projection,
verifying that every layer works together through real infrastructure.

### Command Through to Projection

```gherkin
--8<-- "guides/testing/integration-tests/integration/features/order_flow.feature:feature"
```

### Persistence Round-Trip

```gherkin
--8<-- "guides/testing/integration-tests/integration/features/persistence.feature"
```

## Step Definitions for Integration Tests

Step definitions are written the same way as in application tests. They import
your domain and use `domain.process()` and `domain.repository_for()`:

```python
# fragment
--8<-- "guides/testing/integration-tests/integration/test_order_flow.py:steps"
```

The persistence feature's steps go in `tests/integration/test_persistence.py`:

```python
# fragment
--8<-- "guides/testing/integration-tests/integration/test_persistence.py:steps"
```

## Separating Integration Tests

Use Gherkin tags and pytest markers to separate integration tests from fast
in-memory tests:

```gherkin
@integration
Feature: Persistence
    ...
```

Run them selectively:

```shell
# Fast local development — skip integration tests
pytest tests/ -m "not integration"

# CI pipeline — run everything
pytest tests/

# Run only integration tests
pytest tests/ -m integration
```

You can also separate them by directory structure:

```
tests/
├── conftest.py                  # Shared root fixtures
├── unit/                        # Domain model tests (always fast)
│   └── ...
├── bdd/                         # Application tests (in-memory)
│   └── ...
└── integration/                 # Integration tests (real infra)
    ├── conftest.py              # Real adapter configuration
    ├── features/
    │   ├── order_flow.feature
    │   └── persistence.feature
    ├── test_order_flow.py
    └── test_persistence.py
```

## Testing with Different Adapters

!!!tip "Prefer `--protean-env` for adapter switching"
    Instead of writing per-directory `conftest.py` overrides, consider using
    Protean's built-in **dual-mode testing** support. Define a `[memory]`
    overlay in `domain.toml` and switch modes from the command line:

    ```shell
    pytest --protean-env memory   # In-memory — fast, no Docker
    pytest                        # Real adapters — default (test) overlay
    ```

    No test code or fixture changes needed. See the
    [Dual-Mode Testing](../../patterns/dual-mode-testing.md) pattern for the
    complete setup.

For projects that need finer-grained control or want to switch individual
adapters independently, use environment variables to switch configuration.
This fixture goes in `tests/integration/conftest.py`, and `domain` is your
application's domain (`from myapp import domain`):

```python
# fragment
--8<-- "guides/testing/integration-tests/integration/conftest.py:conftest"
```

Then switch adapters from the command line:

```shell
# Default: in-memory
pytest tests/integration/

# With PostgreSQL
TEST_DB=postgresql DATABASE_URL=postgresql://localhost/myapp_test pytest tests/integration/

# With SQLite
TEST_DB=sqlite pytest tests/integration/
```

The integration feature files and step definitions then run unchanged against
whichever adapter `TEST_DB` names. The domain logic is identical, only the
infrastructure changes.

## Per-Test Data Cleanup

`DomainFixture.domain_context()` automatically resets data in all providers,
brokers, and the event store after each test. If you use the recommended
`_ctx` fixture pattern above, **no additional cleanup fixture is needed**.

## Coverage Reporting

Run your full test suite with coverage to verify you're hitting the 100%
target on business logic:

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
