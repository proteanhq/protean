# Testing Protean

Protean places a high emphasis on testing to ensure the framework's stability, correctness, and reliability. The project follows test-driven development practices. Add tests with every new feature or bug fix.

Protean uses `pytest` as the testing tool, because it allows for simple unit tests as well as complex functional testing. Protean uses `pytest` fixtures to manage test setup and teardown, ensuring tests are isolated and repeatable. The use of `pytest` also enables easy integration with other tools and plugins, such as coverage reporting and parallel test execution.

## `protean test` Command and Options

Protean provides a built-in command for running tests:

```shell
protean test [OPTIONS]
```

Options:

- `-c, --category [CORE|EVENTSTORE|DATABASE|BROKER|COVERAGE|FULL|PR]`: Specifies which category of tests to run
- `-n, --workers TEXT`: Worker processes for the core suite in `CORE` and `PR`, and for the tests that need no service in `FULL` and `COVERAGE`. The value is a number, `auto`, or `logical` (the default, one per logical CPU). `0` runs them in one process. You can also set it with the `PROTEAN_TEST_WORKERS` environment variable.
- `-a, --adapter TEXT`: `PR` only. An adapter, or a group of adapters, from `tests/adapters.toml` to run. Repeat it for more. Without it, `PR` runs the adapters every pull request runs; with it, only the ones you name.
- `--no-core`, `--no-adapters`: `PR` only. Skip the core suite, or the adapter suites (not both).

Categories:

- `CORE`: Runs core tests without external dependencies (default)
- `EVENTSTORE`: Runs the `eventstore` tests on each configured event store, and the event-store conformance suite on Message DB
- `DATABASE`: Runs tests for all configured database adapters. Tests are
  capability-gated. Each provider only runs tests matching its declared
  capabilities (e.g., `basic_storage`, `transactional`, `raw_queries`,
  `native_json`). See [Adapter Conformance
  Testing](../../reference/testing/conformance.md) for details.
- `FULL`: Runs the complete test suite for all adapters
- `COVERAGE`: Runs the complete test suite with all adapters and generates coverage report
- `PR`: Runs what a pull request's CI runs: the core suite and the adapter suites from `tests/adapters.toml`, all under coverage. `protean test -c PR -a elasticsearch` runs the core suite and the Elasticsearch suites only. A pull request that touches Elasticsearch runs the PostgreSQL and Redis suites too; `protean test -c PR -a postgresql -a redis -a elasticsearch` runs what its CI runs.

Example:

```shell
protean test -c DATABASE
```

> **Note**: Make sure that the underlying database services are running within Docker before executing tests in the `DATABASE`, `EVENTSTORE`, or `FULL` categories. Use the `make up` command to start the necessary services.

`protean test -c DATABASE` runs the database tests against multiple adapters (MEMORY, POSTGRESQL, SQLITE).

### Which runs include the conformance suites

The port conformance suites live in `tests/conformance/<port>/` (see [Adapter Conformance Testing](../../reference/testing/conformance.md)). The core run collects `tests/`, so it runs each suite once on the port's default adapter: `inline` for `broker`, `memory` for the other three. That covers `CORE`, `PR` with or without `--no-adapters`, and the in-memory pass of `FULL` and `COVERAGE`. No category adds a second run on a default adapter.

An entry in `tests/adapters.toml` names the other adapters with its `conformance` key, a list of `"<port>:<adapter>"` pairs. For each pair, `protean test` runs pytest over `tests/conformance/<port>/` with `--port <port> --adapter <adapter>`, under coverage:

- in the entry's leg, such as `protean test -c PR --no-core -a message-db`. An entry whose lane is `core` or `off` has no leg.
- in `protean test -c FULL` and `protean test -c COVERAGE`, unless the entry's lane is `off`.

The `message-db` entry lists `event_store:message_db`, so both run the event-store suite on Message DB.

`protean test -c EVENTSTORE` does not read `tests/adapters.toml`. It runs the event-store suite on each event store in its own store list except memory, without coverage, like its `eventstore` runs. Its list holds `MEMORY` and `MESSAGE_DB`, so it runs the suite on Message DB.

The entry's `paths` must include `tests/conformance/<port>/`, so a change to the suite runs the leg. `tests/cli/test_adapter_manifest.py` fails when a path is missing.

### Parallel runs

`CORE` runs on [pytest-xdist](https://pytest-xdist.readthedocs.io/) with `--dist loadfile`, so all the tests in one file run on the same worker. `PR` runs its core suite the same way.

`FULL` and `COVERAGE` start with two passes over the whole suite, one after the other. The first runs every test that needs no service on pytest-xdist, as `CORE` does. The second runs the tests that need one, in a single process. A test needs a service when it runs only with a flag such as `--redis` or `--mssql`. Such a test carries that marker or is in a package of that name, such as `tests/adapters/repository/sqlalchemy_repo/mssql/`. The suite's own `--service-tests=none` and `--service-tests=only` options make the split. After the two passes, `FULL` and `COVERAGE` run the separate adapter suites in parallel, up to three at a time.

Tests that use a service run in one process, because within one adapter's suite they share a database, Redis keys, Elasticsearch indexes, and the Message-DB `$all` stream. `EVENTSTORE`, `DATABASE` and `BROKER` never use pytest-xdist and ignore `--workers`. With `--sequential`, `FULL` and `COVERAGE` run every suite one at a time and in one process.

A test that passes alone but fails in a parallel run depends on state that another test left behind. The root `conftest.py` already resets the domain, the adapters, the global logging configuration, and the structlog context after every test. Fix that shared state in the test or its fixtures. To run the suite in one process, for example to rule out ordering, run:

```shell
protean test --workers 0
```

## Multi-Version Testing with Nox

Protean supports Python 3.11, 3.12, 3.13, and 3.14, and tests against the 3.15 prerelease. To run tests across all supported versions locally, Protean uses [Nox](https://nox.thea.codes/) with a `noxfile.py` at the repository root.

### Prerequisites

Install the four stable Python versions with [pyenv](https://github.com/pyenv/pyenv). List them in `.python-version`, so that `python3.11`, `python3.12`, `python3.13`, and `python3.14` are available on `$PATH`:

```shell
pyenv install 3.11 3.12 3.13 3.14
```

Nox also has a `3.15` session. It runs only if a `python3.15` is on your `$PATH`, and Nox skips it otherwise. To exercise it locally, install the current 3.15 prerelease as well (for example `pyenv install 3.15.0rc1`).

### Running

```shell
make test-matrix            # Core tests across all Python versions
make test-matrix-full       # Full suite across all versions (starts Docker services)
```

You can also target a single version:

```shell
uv run nox -s tests-3.13    # Core tests on 3.13 only
uv run nox -s full-3.12     # Full suite on 3.12 only
```

Nox runs sessions **serially** (not in parallel) because the full suite shares database services started by `make up`.

### Available Nox Sessions

| Session | Description |
|---------|-------------|
| `tests-3.X` | Core tests (memory adapters) on Python 3.X |
| `full-3.X` | Full test suite (all adapters) on Python 3.X |

## Docker Containers

Protean uses Docker Compose to provide a consistent development and testing environment. The included `docker-compose.yml` file defines services for all supported adapters:

```yaml
services:
  elasticsearch:
    image: ${ELASTICSEARCH_IMAGE:-elasticsearch:8.7.0}
    # configuration...

  redis:
    image: ${REDIS_IMAGE:-redis:7.0.11}
    # configuration...

  postgres:
    image: ${POSTGRES_IMAGE:-postgres:15.2}
    # configuration...

  message-db:
    image: ${MESSAGE_DB_IMAGE:-ethangarofolo/message-db:1.3.1}
    # configuration...

  mysql:
    image: ${MYSQL_IMAGE:-mysql:8.4}
    # configuration...

  mariadb:
    image: ${MARIADB_IMAGE:-mariadb:11.4}
    # configuration...

  ...
```

The development environment includes:

- PostgreSQL for relational database testing
- MySQL and MariaDB, both served by the one `mysql` provider
- SQL Server for the MSSQL provider
- Elasticsearch for document store testing
- Redis for caching and simple key-value storage
- Message-DB for event sourcing and messaging

Services listen on non-standard ports so they do not clash with anything else
on the machine: PostgreSQL 55432, Message-DB 55433, Redis 56379, SQL Server
51433, MySQL 53306, MariaDB 53307, Elasticsearch 59200. The ports live in
`tests/shared.py`, which lists the other files to change alongside them.

To start the development environment, Protean provides easy `make` commands:

```shell
make up
```

Refer to `Makefile` for a full list of supported `make` commands.

These containers are also used in CI pipelines to ensure consistent testing across environments.

### Service image mirror (GHCR)

CI does not pull these images from Docker Hub. Instead it pulls them from a
public mirror in this org's GitHub Container Registry (GHCR), at
`ghcr.io/proteanhq/mirror/<image>`. With the mirror, CI avoids Docker Hub's
anonymous pull rate limit on shared CI runners. The mirror also lets pull
requests from forks run the full suite with no secrets, because a fork's
`GITHUB_TOKEN` can read public GHCR packages. The
`.github/workflows/mirror-images.yml` workflow refreshes the mirror weekly (and
on demand via **Run workflow**).

Local `make up` still pulls from upstream registries by default, so no mirror
access is needed for day-to-day development. To point a service at the mirror
instead, override its image via an environment variable before `make up`:

```shell
POSTGRES_IMAGE=ghcr.io/proteanhq/mirror/postgres:16 make up
```

The mirror carries the tags CI uses (which differ from the compose defaults), so
use these exact refs when overriding:

| Override variable | Mirror ref |
|-------------------|------------|
| `ELASTICSEARCH_IMAGE` | `ghcr.io/proteanhq/mirror/elasticsearch:8.7.0` |
| `REDIS_IMAGE` | `ghcr.io/proteanhq/mirror/redis:7` |
| `POSTGRES_IMAGE` | `ghcr.io/proteanhq/mirror/postgres:16` |
| `MESSAGE_DB_IMAGE` | `ghcr.io/proteanhq/mirror/message-db:1.3.1` |
| `MSSQL_IMAGE` | `ghcr.io/proteanhq/mirror/mssql-server:2022-latest` |
| `MYSQL_IMAGE` | `ghcr.io/proteanhq/mirror/mysql:8.4` |
| `MARIADB_IMAGE` | `ghcr.io/proteanhq/mirror/mariadb:11.4` |

## Tests Organization

Protean follows a systematic approach to test organization and naming:

- Test files are named with a `test_` prefix (e.g., `test_domain.py`) or a `_test` suffix (e.g., `domain_test.py`).
- Test functions within these files should also be prefixed with `test_` followed by a descriptive name of what's being tested.
- Test classes should be named with `Test` prefix followed by the name of the component being tested (e.g., `TestDomain`).
- The test organization mirrors the package structure, with each core component having its own test directory.

### Configuration

Protean uses `domain.toml` configuration files to define test domains. The main `tests/domain.toml` provides default settings (sample below):

```toml
debug = true
testing = true
secret_key = "secret-key"
identity_strategy = "uuid"
identity_type = "string"
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "memory"

[databases.memory]
provider = "memory"

[databases.sqlite]
provider = "sqlite"
database_uri = "sqlite:///test.db"

[brokers.default]
provider = "inline"

[caches.default]
provider = "memory"
```

This configuration establishes a consistent testing environment, setting key parameters like:

- Enabling debug and test modes
- Setting up default database providers (memory and SQLite)
- Configuring default brokers and caches
- Setting identity and event processing strategies for a dev environment

The root `conftest.py` file provides common test fixtures and configuration for the entire test suite. It includes:

- Global pytest configuration
- Command-line options for specific test types (e.g., `--slow`, `--database`, `--postgresql`)
- Fixtures for database and event store configuration
- The critical `test_domain` fixture that creates a clean test domain for each test
- The `db` fixture that creates and drops database artifacts for tests
- The `run_around_tests` fixture that resets data after tests complete

### Distribution

The Protean test suite is organized into specialized directories matching the framework's architecture:

- Each core element has its own test directory (e.g., `tests/aggregate/`, `tests/entity/`, `tests/repository/`)
- Common utility tests are in the tests root (e.g., `test_registry.py`, `test_utils.py`)
- Integration tests that span multiple components are organized by functionality

Within each core element's test directory, the tests are further divided:

- Each aspect of functionality is tested separately
- Complex components are tested in dedicated files for better organization
- Tests progressively build complexity, starting with simple unit tests and progressing to more complex integration scenarios

For example, in the `tests/domain/` directory, different aspects of domain functionality are split into individual files:

- `test_domain_config.py`
- `test_domain_traversal.py`
- `test_domain_shell_context.py`

### Local Fixtures

For specialized test requirements, you can create local `conftest.py` files within test subdirectories. These local configurations:

- Override fixtures defined in the root `conftest.py`
- Define fixtures specific to tests in that directory
- Create test data relevant to the component being tested
- Allow for specialized domain configurations without affecting other tests

Local `domain.toml` files can also be created to customize domain configuration for specific test directories. The resolution order follows pytest's fixture resolution, with more specific configurations (closer to the test) taking precedence.

### Pytest Markers

Pytest markers are used to categorize tests and control their execution. Protean uses the following markers:

- `slow`: Tests that take longer to run and may be skipped during development
- `pending`: Tests that are not yet fully implemented or are waiting for a feature
- `sqlite`, `postgresql`, `elasticsearch`, `redis`, `message_db`: Tests for specific adapters
- `database`: Tests that require database interaction
- `broker_common`: Tests for message broker functionality
- `eventstore`: Tests for event store functionality
- `no_test_domain`: Tests that should not use the default test domain
- `flaky`: Timing-sensitive or non-deterministic tests. The marker records the
  fragility and lets you run just those tests, in isolation, with
  `make test-flaky`. It does **not** exclude them from any run: `protean test`
  and the CI suite still execute them, so a marked test that starts failing
  still turns the build red. Treat the marker as a note to the next reader, not
  a quarantine. Rather than fix a timing test with a longer sleep, see
  [Read the recorded time instead of racing a sleep](#read-the-recorded-time-instead-of-racing-a-sleep).

**Capability markers** (used by the generic adapter test suite):

- `basic_storage`: CRUD, filtering, bulk operations, ordering
- `transactional`: Transaction support (real or simulated)
- `atomic_transactions`: Real database transactions only
- `raw_queries`: Native query support
- `schema_management`: DDL operations (create/drop tables)
- `native_json`: Native JSON column type
- `native_array`: Native array column type

These markers can be used with pytest's `-m` option to selectively run tests for a specific database, e.g., `pytest -m database --db=POSTGRESQL --ignore=tests/support/`.

Refer to `tests/conftest.py` for other database options.

#### Running the PostgreSQL leg on each driver

The `postgresql` provider supports psycopg 3 and psycopg2. `--db POSTGRESQL`
uses a plain `postgresql://` URL, which picks psycopg 3. `--db
POSTGRESQL_PSYCOPG2` uses a `postgresql+psycopg2://` URL, so the same
conformance battery runs on psycopg2:

```shell
uv run pytest --postgresql --db POSTGRESQL tests/adapters/repository/generic
uv run pytest --postgresql --db POSTGRESQL_PSYCOPG2 tests/adapters/repository/generic
```

#### Running the MySQL leg

The `mysql` provider serves MySQL and MariaDB. SQLAlchemy reports a different
dialect name for each, so both are in the matrix. `make up` starts both
containers. To run the conformance battery against them:

```shell
uv run pytest --mysql --db MYSQL tests/adapters/repository/generic
uv run pytest --mysql --db MARIADB tests/adapters/repository/generic
```

`--mysql` also enables the server-specific tests in
`tests/adapters/repository/sqlalchemy_repo/mysql/`, which run against both
MySQL and MariaDB. `native_array` is the only capability the provider does not
claim, so those tests are deselected.

### `protean test test-adapter`

In addition to `protean test`, Protean provides a dedicated subcommand for
validating that an adapter correctly implements its declared capabilities:

```shell
protean test test-adapter --provider postgresql --uri "postgresql://..."
protean test test-adapter --port event_store --provider message_db --uri "postgresql://..."
```

`--port` picks the port: `database` (the default), `broker`, `cache` or
`event_store`. `--provider` names the adapter registered for that port, `--uri`
sets its connection URI, and `--config` merges a JSON object into its
configuration. For `broker`, `cache` and `event_store`, the command runs the
port's conformance suite once for the tests that need no flag (the `unmarked`
row) and then once per capability flag. For `database`, it runs once per
capability marker, such as `basic_storage`, and `--uri` and `--config` set only
the configuration that reads the provider's capabilities. A flag or marker the adapter
does not declare is reported as SKIP.

The suites are not in the wheel, so the command runs from a source checkout.
See [Adapter Conformance Testing](../../reference/testing/conformance.md) for
full CLI reference and usage examples.

## Writing tests that last

A test lasts when it fails only because the behaviour it checks has changed. A refactor that keeps the behaviour must leave it green, and a bug in that behaviour must turn it red. The rules below follow from that.

The good examples on this page are test modules under `docs_src/community/contributing/testing/`, and `tests/docs/community/contributing/test_testing.py` runs each one under pytest. Every example block carries the `# fragment` marker. A bad example carries the marker so that it does not run. A good example carries the marker because `test_testing.py` already runs its file (see [Code on documentation pages](#code-on-documentation-pages)).

### Test behaviour through the public API

Build objects the way a user of the framework builds them, and check what a user can see: a public attribute, a return value, a raised exception. Never build an object with `__new__`, set a private attribute, or assert on one. A test that reaches into private state breaks when the internals change, even if the behaviour did not, and it can pass for a state no user can reach.

This test skips the constructor and checks a private attribute it set itself:

```python
# fragment
def test_money_amount():
    money = Money.__new__(Money)
    money._amount = -5.0
    assert money._amount == -5.0
```

These tests build `Money` normally and check its public attributes and the error it raises:

```python
# fragment
--8<-- "community/contributing/testing/003.py:public_api"
```

### Test one behaviour per test and name it for that behaviour

When a test checks one behaviour, its name says what broke when it fails. The test below places an order, cancels it and checks the error for a draft order. It stops at the first failing assert and does not show whether the later steps still work:

```python
# fragment
def test_order():
    order = Order()
    order.place()
    assert order.status == "PLACED"
    order.cancel()
    assert order.status == "CANCELLED"
    with pytest.raises(ValidationError):
        Order().cancel()
```

Split it into one test per behaviour. Each name reads as a statement of what the code does:

```python
# fragment
--8<-- "community/contributing/testing/004.py:one_behaviour"
```

### Assert the exact value

Compare against the value you expect: `assert result == 3`. A bare `assert result` passes for any truthy value, so it passes when the total is wrong too. The same goes for `is not None`, a length check, or `"amount" in str(exc.value)` when the full message is known.

```python
# fragment
def test_order_total():
    order = Order()
    order.add_line(price=10.0, quantity=2)
    order.add_line(price=5.0, quantity=3)
    assert order.total
```

```python
# fragment
--8<-- "community/contributing/testing/005.py:exact_value"
```

### Keep `if` and `for` out of the test body

A loop in a test stops at the first failing input and does not say which inputs ran. An `if` in a test means the test checks different things on different runs, and one of the branches may never run at all. Use `pytest.mark.parametrize` for several inputs. pytest then runs and reports each input as its own test.

```python
# fragment
def test_email_addresses():
    for address in ["ana@example.com", "ana.example.com"]:
        if "@" in address:
            assert Email(address=address).address == address
        else:
            with pytest.raises(ValidationError):
                Email(address=address)
```

```python
# fragment
--8<-- "community/contributing/testing/006.py:parametrize"
```

### Mock only an external service, the clock, or a failure you cannot cause

A mock replaces real code with code the test wrote, so the test stops checking the real code. A mock is acceptable in three cases:

- an external service, such as a payment provider or an email API, that a test cannot call
- the clock, when the code reads the current time
- a failure you cannot produce for real, such as a full disk or a dropped connection

For everything else, use the real object. For persistence, use the in-memory adapters. The test configuration in `tests/domain.toml` sets the `memory` database provider, the `inline` broker and the `memory` cache (see [Configuration](#configuration)). In the test below, a `MagicMock` replaces the repository. The test still passes if `pay_invoice` stores the wrong status, because the mock records the `add` call and stores nothing:

```python
# fragment
def test_paying_an_invoice():
    repo = MagicMock()
    repo.get.return_value = Invoice(amount=30.0)
    with (
        patch.object(current_domain, "repository_for", return_value=repo),
        patch.object(gateway, "charge", return_value="pay-1"),
    ):
        pay_invoice("inv-1")
    repo.add.assert_called_once()
```

This test stores the invoice in the in-memory database, patches only the call to the payment provider, and reads the invoice back:

```python
# fragment
--8<-- "community/contributing/testing/007.py:mock_the_gateway"
```

### Read the recorded time instead of racing a sleep

A test that sleeps and then asserts depends on how busy the machine is. It is slow when the sleep is long and flaky when it is short. When code schedules something, it records when: a delay, or a time such as `next_attempt_at`. Assert the value the code recorded. To test the other side, move the recorded times into the past by more than the delay and check again.

```python
# fragment
def test_retry_becomes_due():
    retry = Retry(delay=timedelta(seconds=0.2))
    retry.schedule()
    time.sleep(0.2)
    assert retry.is_due()
```

```python
# fragment
--8<-- "community/contributing/testing/008.py:recorded_time"
```

### Extend an existing test before writing a new one

Before you add a test file, look for the tests that already cover the code you changed. The test folders follow the source packages (see [Distribution](#distribution)):

| Source | Tests |
|--------|-------|
| `src/protean/core/aggregate.py` | `tests/aggregate/` |
| `src/protean/core/entity.py` | `tests/entity/` |
| `src/protean/core/value_object.py` | `tests/value_object/` |
| `src/protean/adapters/repository/` | `tests/adapters/repository/` |
| `src/protean/server/` | `tests/server/` |

Search there for the name of the function or class you changed:

```shell
grep -rln "add_comments" tests/aggregate/ tests/entity/
```

If a test already sets up the case, add the new behaviour as a test next to it, or as one more `parametrize` input. A new file for a small change spreads one behaviour over several places.

### Do not write a test only to reach a line

The `codecov/patch` check needs 96% of the changed lines to be covered. A test can run a line without checking what the line does. It counts toward the 96%, and it still passes when the line is wrong. The usual shape is a test that builds an object with `__new__`, sets a private attribute by hand to force a guard, and asserts on private state. No user of the framework can reach that state, so the test checks nothing a user depends on.

When a changed line is not covered, do one of these:

- Reach the line through a behaviour. Find the public call that runs it, and write the test for what that call does.
- If no public path reaches the line, the line is dead code or a guard that cannot fire. Remove it, or mark it `# pragma: no cover` with the reason on the same line:

```python
# fragment
    if store is None:  # pragma: no cover - domain.init() always sets a store first
        raise ConfigurationError("no event store configured")
```

A `pragma` with no reason leaves the next reader to work out why the line is excluded.

### Delete a test when the evidence says it adds nothing

A test may be deleted or merged into another when the behaviour it covered no longer exists in the code. Otherwise, both of these checks must pass:

- **Coverage.** For every source module the deleted or merged tests covered, `coverage json` gives the same `missing_lines` and `missing_branches` before and after the change. Compare the line lists, because one line can be lost while another is gained and the percentage stays the same. Run the "before" measurement twice. If a line differs between those two runs, list it in the pull request. Leave that line out of the comparison.
- **Mutation.** For a module with a [mutation testing](mutation-testing.md) target, the run after the change has no new survivor compared with the run before. Its not-covered count is also no higher. A mutant is a small change mutmut makes to the source. It survives when the tests that reach it run and pass, and it is not covered when no test reaches it. `make mutation` prints the survivor names and the not-covered count. Compare those two, not the score. The score divides by the mutants some test reached. If you delete the only test that reaches a mutant, the mutant moves to not-covered, so the score can stay the same or rise.

"Before" is the merge-base of your branch with `main`. `main` itself moves as other pull requests merge. Measure it in a second worktree, with the same commands you use on your branch:

```shell
git worktree add ../before $(git merge-base origin/main HEAD)
cd ../before
uv sync --all-extras --all-groups
uv run protean test -c PR --no-adapters
uv run coverage json -o coverage-before.json
make mutation TARGET=entity
```

`uv sync` gives the worktree its own virtual environment, so the tests import the code at the merge-base and not your branch. Run the same commands on your branch for the "after" numbers. `protean test -c PR --no-adapters` measures the core tests. A test with a service marker never runs in the core lane, so measure it with the adapter leg that runs it, for example `uv run protean test -c PR -a redis --no-core`. The pull request lists each deleted or merged test, the test that now covers its behaviour, the before and after numbers, and the commands that produced them.

`make test-audit` lists duplicate and private-state tests to review (see [Auditing the suite](#auditing-the-suite)). A test from that list still needs this evidence before you delete it.

### Prefer one property test to a long list of examples

Some rules are properties: they hold for every input. For such a rule, a list of examples checks only the inputs the test's author thought of. A property test with [Hypothesis](https://hypothesis.readthedocs.io/) generates the inputs. When an input fails, Hypothesis shrinks it to a simpler failing input. Hypothesis is in the `test` dependency group.

```python
# fragment
@pytest.mark.parametrize(
    "amount, currency",
    [(0.0, "USD"), (1.5, "USD"), (99.99, "EUR"), (1000.0, "INR"), (0.01, "EUR")],
)
def test_money_round_trip(amount, currency):
    rebuilt = Money(**Money(amount=amount, currency=currency).to_dict())
    assert (rebuilt.amount, rebuilt.currency) == (amount, currency)
```

```python
# fragment
--8<-- "community/contributing/testing/009.py:property"
```

The test compares the rebuilt fields with the generated inputs, so a failure names the field that did not survive the round trip. `deadline=None` turns off Hypothesis's time limit for each input, which building a domain object can exceed on a busy CI machine.

`tests/serialization/test_roundtrip_value_object.py` checks the same round trip for every field type, with strategies shared from `tests/serialization/strategies.py`. Keep examples for the cases a property does not describe, such as one known boundary or a bug that was fixed.

## Important Fixtures

Protean provides several important fixtures to simplify test setup and make tests more consistent:

### `test_domain`

The `test_domain` fixture creates a fresh Protean domain for each test. It:

- Creates a new Domain instance with test configuration
- Configures the domain with database and event store settings
- Initializes the domain and provides a domain context
- Is automatically used in all tests unless the `no_test_domain` marker is applied

Example usage:

```python
--8<-- "community/contributing/testing/001.py:test_domain_fixture"
```

### `db`

The `db` fixture sets up and tears down the database:

- Automatically associated with tests marked with `database`
- Creates all database artifacts (tables, collections, etc.) before tests
- Drops all artifacts after tests complete
- Resets the registry to ensure a clean state for subsequent tests

### `run_around_tests`

The `run_around_tests` fixture runs automatically for all tests and:

- Resets data in all providers after each test
- Ensures tests don't interfere with each other
- Maintains test isolation even when using memory providers

### `register_elements`

This fixture registers domain elements for testing:

- Registers aggregates, entities, value objects, etc. with the test domain
- Creates a clean environment with only the elements needed for the specific test
- Helps isolate tests and prevent unexpected interactions

### `auto_set_and_close_loop`

For asynchronous tests, this fixture:

- Sets up an event loop for testing async code
- Ensures the loop is properly closed after tests
- Works with pytest-asyncio to simplify async testing

### `db_config`

The `protean test` command uses fixtures to target different adapters. The below fixtures are present in `tests/conftest.py`:

The `db_config` fixture is used by `protean test` command and configures database adapters based on command-line options:

- Returns configuration for MEMORY, POSTGRESQL, ELASTICSEARCH, or SQLITE
- Used to dynamically select the database to test against
- Reads the `--db` option, which specifies the database type

To configure Protean to use a local database on your system, edit the connection settings that the `db_config` fixture returns.

### `store_config`

The `store_config` fixture configures event store adapters in the same way,
based on command-line options:

- Returns configuration for MEMORY or MESSAGE_DB
- Used to dynamically select the event store to test against
- Reads the `--store` option, which specifies the store type

## Code on documentation pages

`tests/docs/test_doc_pages_run.py` runs every `python` (or `py`) block on every page under `docs/`, except the pages in `docs/adr/` and `docs/api/`. The blocks of a page run top to bottom in one namespace, so a block can use a name an earlier block defined. Each page starts with a `domain` and the public names from `protean` and `protean.fields`. After the last block, every domain the page registered an element with is initialized, so a `part_of` must resolve by the end of the page.

Put runnable code in a file under `docs_src` and include it on the page by a named section. A section starts at a line <code># --8<-- &#91;start:place_order]</code> and ends at a line <code># --8<-- &#91;end:place_order]</code>. Between them goes the code the page shows:

```python
--8<-- "community/contributing/testing/002.py:place_order"
```

The page includes it with `--8<-- "path/to/file.py:place_order"` inside a `python` fence. The test replaces that line with the section's code before it runs the block. Prefer a named section to a line range like `file.py:10:24`, because a line range points at the wrong lines once the file changes.

A block whose first line is `# fragment` does not run. Use it only for:

- a signature, such as `Index.from_sql(dialect, ddl, name=None) -> RawIndex`
- part of a class or a method
- a wrong example shown on purpose
- code that needs a service the core test lane does not run, such as a database
- code that starts a server or otherwise blocks

A `>>>` REPL session uses a `pycon` fence, and an IPython session uses `ipython`. Neither runs.

Give each page its own folder under `docs_src`, at the page's path, and number the files in the order the page shows them. The examples for `docs/guides/change-state/unit-of-work.md` are `docs_src/guides/change-state/unit-of-work/001.py` and `002.py`.

A test already runs some files, such as a test module or a `conftest.py`. When a block includes a section of such a file, mark the block `# fragment`. The page runner would otherwise run that code again in the page's namespace. Put `# fragment` on the line above the include.

Each page you move to `docs_src` gets behaviour tests in `tests/docs`, in one file per page at the page's path. Folder names use underscores, and the file name starts with `test_`: the tests for `docs/guides/change-state/unit-of-work.md` are in `tests/docs/guides/change_state/test_unit_of_work.py`. A test loads an example with `load_example(path)` from `tests/docs/support.py`, then checks what the example does. The `path` is relative to `docs_src`. Pass the path as a string literal.

`tests/docs/test_docs_src_is_tested.py` fails on a `docs_src` file that no test loads. It finds the loaded files by reading the test source for `load_example` and `run_example_tests` calls with a literal path, and for imports of `docs_src` packages. A file no test loads yet goes into its `ALLOWLIST`. That list is strict too: a listed file that a test now loads fails the check until you remove its entry.

Once a page takes all its code from `docs_src`, add it to `PAGES` in `tests/docs/test_pages_take_code_from_docs_src.py`, in sorted order. On a page in `PAGES`, every Python block is either marked `# fragment` or holds only named-section includes, so the page cannot go back to inline code.

`ruff format` formats the files in `docs_src` and skips Markdown. On a Markdown page, ruff would read an include line such as `--8<-- "guides/x/001.py:full"` as a Python expression and rewrite it, and the include would stop working. The code left inline on a page is signatures, partial code and wrong examples, which keep the layout the page gives them.

If a page's code fails, fix it. If you cannot fix it in the same change, add the page to `ALLOWLIST` in `tests/docs/test_doc_pages_run.py`. Do not mark a block `# fragment` to hide an error. The allowlist is strict: once a listed page passes, the test fails until you remove its entry.

Two checks have no allowlist. Every block that is not a fragment must parse, and every `--8<--` include must point at a file and a section that exist.

## Code Coverage

Protean uses Coverage.py to track test coverage. `coverage` configuration is maintained in `pyproject.toml`.

When you run the full test suite with `protean test -c FULL` (or the pull request lane with `protean test -c PR`), the command collects coverage data from tests across multiple adapters and combines it:

1. Each test run generates a `.coverage` file
2. The `coverage combine` command merges these files
3. The `coverage report` command generates a summary

You can also view coverage diffs and look for lines missing coverage with the `protean test -c COVERAGE`. The command generates an HTML report that visually represents the coverage data, making it easy to identify untested code paths.

It compares the current branch's coverage against the main branch to highlight changes in coverage, which is especially useful for pull request reviews. Codecov checks the lines each pull request changes, as described under Constraints.

### Constraints

Protean enforces coverage constraints to ensure code quality:

- Coverage is checked as part of the CI pipeline
- Overall project coverage is reported on each pull request but does not fail it

If tests cover fewer than 96% of the lines a pull request changes, the `codecov/patch` check fails and the coverage report lists the uncovered lines. Meet the gate in one of two ways:

- Write a test for a behaviour that runs the line, and assert what that behaviour does.
- If no public path reaches the line, remove it, or mark it `# pragma: no cover` with the reason on the same line.

For why a test that only runs the line does not count, see [Do not write a test only to reach a line](#do-not-write-a-test-only-to-reach-a-line).

### Auditing the suite

`make test-audit` reports tests worth a second look. It runs the core suite,
which needs no Docker, and writes `.test-audit/report.md` and
`.test-audit/report.json`:

```shell
make test-audit
```

The report has four sections:

- **Duplicate candidates.** The suite runs under coverage.py, and the audit
  switches coverage.py's context (the label it stores each recorded arc
  under) to the running test. An arc is a step from one line to the next. The
  audit lists a test when its arcs are a subset of another test's arcs. The
  listing shows the covering test next to it. The list is grouped by top-level
  test folder. Tests that cover no source arcs of their own are listed apart.

  Only arcs run in the test body count. Fixture setup and teardown, and any
  child process the test starts, are not counted. Code that runs once per
  worker process, such as an import or a cache filled on first use, counts
  only for the first test on that worker. A test that failed or xfailed in
  this run is left out, and so is a test whose every case was skipped.
- **Private-state and coverage-named tests.** A scan of `tests/` (except
  `tests/support/`) lists calls to `X.__new__(X)`, writes to private
  attributes, patches of private names, files named `*_coverage.py`, and
  docstrings or comments that say a test exists for coverage. The scan does not
  list a write through `self` or `cls` in a test class, or a write to a mock
  the same function created. The two files that guard doc and deprecation
  coverage are not scanned, and the report says why.
- **The 50 slowest tests**, timed in a run without coverage.
- **Order-dependent tests.** The suite runs again in a random order with
  [pytest-randomly](https://github.com/pytest-dev/pytest-randomly). The
  coverage run keeps the default order. When a test fails in the random-order
  run and also failed in the coverage run, the audit lists it as a plain
  failure. The audit runs every other test that fails in the random-order run
  again alone. It lists a test that passes alone as order-dependent. A flaky
  test can pass alone too, so check each one. A test that is skipped or xfailed
  alone is listed on its own, since the re-run did not show whether it passes.
  The section shows the seed.
  `uv run python scripts/test_audit.py --seed <seed>` shuffles each file the
  same way again.

The report ranks candidates for review. The audit changes no test and writes
only under `.test-audit/`. A test listed as a duplicate can still check a
value the covering test does not.

pytest-randomly is installed with the `test` group and turned off in
`addopts`, so `protean test`, CI and `make mutation` run the suite in its usual
order. The audit turns it on for its own run. Some tests start a pytest run of
their own, such as the one `protean verify` runs in a temporary project. That
run keeps the usual order too, because `tests/conftest.py` sets
`PYTEST_ADDOPTS=-p no:randomly` for each test.

## Github Actions

Protean's CI runs in three lanes, so a pull request's cost follows the size of the change rather than the number of adapters:

- **Pull request.** Lint, mypy, and the DX pack. The in-memory core suite on 3.11, 3.12, 3.13, and 3.14 (the 3.14 leg at the lowest supported dependency versions). The `Adapters` check: PostgreSQL and Redis on every pull request, plus each adapter whose files the pull request changes. `tests/adapters.toml` lists every adapter, its paths, and the services it needs; a test fails if an adapter module is missing from it. The `Coverage` job combines the core and adapter coverage into one upload, and Codecov's `codecov/patch` check requires 96% of the changed lines to be covered.
- **Push to `main`.** The same, plus the full adapter suite (`protean test -c FULL`) on 3.14, which uploads `main`'s coverage and enforces the 94% project floor. A red run opens or updates a `ci-failure` issue.
- **Nightly.** The full adapter suite on every Python version, including the 3.15 prerelease (non-blocking). A red run opens or updates the same `ci-failure` issue.

Pull requests cannot be merged until the required checks pass. The checks run the tests on every supported Python version, catch regressions, and keep code coverage high.

The pipeline also deploys documentation updates when changes are merged to the main branch.
