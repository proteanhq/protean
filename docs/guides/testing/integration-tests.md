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

## Configure the domain for real infrastructure

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

## Run the server in test mode

For integration tests that exercise async message flows (event handlers,
projectors, process managers), use the server's **test mode**. It processes
all available messages and cascading events, then exits.

The examples in this section test the domain below. When you place an order,
the order aggregate raises `OrderPlaced`. An event handler reserves stock and
raises `InventoryReserved`. A second handler then marks the order shipped. The
fixtures set both processing modes to `"async"`. As a result, the two event
handlers run only when the engine runs:

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

Test mode processes cascading events automatically. When a handler raises
another event, the engine processes that event as well. The engine keeps
running until all chains are complete:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:cascade"
```

You can also invoke test mode from the CLI:

```bash
protean server --domain=my_domain --test-mode
```

See [Run the Server](../server/index.md#run-in-test-mode) for CLI details.

## Driving flows with `process_and_wait`

The `Engine(domain, test_mode=True).run()` calls above are the low-level
primitive. For most tests, `protean.testing` provides higher-level helpers.
With these helpers, the **same test body works in both synchronous and
asynchronous processing modes**. The helpers also hand you the events and
errors, so you do not read outbox rows or event-store streams yourself.

`process_and_wait(command, domain)` processes a command through its full
runtime path (`handler → aggregate → UoW commit → outbox → engine →
subscription → projector`) and waits for the effects to settle. In sync mode,
the chain runs inline. In async mode, `process_and_wait` drains a bounded
test-mode engine before it returns. It returns a `ProcessResult`:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:process_and_wait"
```

A `ProcessResult` exposes exactly what an integration test asserts on:

- `result`: The handler's return value (sync) or the enqueued command's store position (async).
- `events`: An `EventLog` of every event raised in the command's correlation chain.
- `error` / `succeeded` / `failed`: the synchronous or submission-time error
  (an unregistered command, an expired deadline, a duplicate key, an enrichment
  `ValidationError`). Asynchronous *handler* failures happen after the command
  is enqueued. The engine absorbs these failures (retries or DLQ).
  `ProcessResult` does not surface them.

### Asserting on events with `EventLog`

`outcome.events` is an `EventLog` with Pythonic access by type or index:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:event_log"
```

### Waiting for a condition with `drain`

`drain` runs the test-mode engine until a predicate is satisfied. Use it in two
cases: you drive the flow yourself, or you need to wait for a later cascade to
settle. It replaces the copy-pasted `for _ in range(N): Engine(...).run()`
loop:

```python
# fragment
--8<-- "guides/testing/integration-tests/001.py:drain"
```

`drain` is bounded by `max_cycles` (default 5) so a never-satisfied `until`
cannot hang the test. `drain` can reach `max_cycles` before the condition
settles. In that case `drain` returns and emits a `UserWarning`, so you always
see an unmet expectation. An engine pass stops once nothing is left to process
and takes at most about a second, so raise `max_cycles` only for flows that
genuinely need more passes.

## Write feature files for full flows

Integration tests exercise complete flows from command to projection,
verifying that every layer works together through real infrastructure.

### Follow a command through to a projection

```gherkin
--8<-- "guides/testing/integration-tests/integration/features/order_flow.feature:feature"
```

### Check that an aggregate survives a persistence round-trip

```gherkin
--8<-- "guides/testing/integration-tests/integration/features/persistence.feature"
```

## Write step definitions for integration tests

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

## Keep integration tests separate from fast tests

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

## Test with different adapters

!!!tip "Prefer `--protean-env` for adapter switching"
    Instead of writing per-directory `conftest.py` overrides, consider using
    Protean's built-in **dual-mode testing** support. Define a `[memory]`
    overlay in `domain.toml`. Then switch modes from the command line:

    ```shell
    pytest --protean-env memory   # In-memory — fast, no Docker
    pytest                        # Real adapters — default (test) overlay
    ```

    No test code or fixture changes needed. See the
    [Dual-Mode Testing](../../patterns/dual-mode-testing.md) pattern for the
    complete setup.

For projects that need finer-grained control or want to switch individual
adapters independently, use environment variables to switch configuration. Put
the fixture below in `tests/integration/conftest.py`. In that fixture, `domain`
is your application's domain (`from myapp import domain`):

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

## Clean up data after each test

`DomainFixture.domain_context()` automatically resets data in all providers,
brokers, and the event store after each test. If you use the recommended
`_ctx` fixture pattern above, **no additional cleanup fixture is needed**.

## Report test coverage

Run your full test suite with coverage to check that you reach the 100% target
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
