# Testing Protean

Protean places a high emphasis on testing to ensure the framework's stability, correctness, and reliability. The project follows test-driven development practices, and all new features or bug fixes should be accompanied by appropriate tests.

Protean uses `pytest` as the testing tool, because it allows for simple unit tests as well as complex functional testing. Protean leverages `pytest` fixtures to manage test setup and teardown, ensuring tests are isolated and repeatable. The use of `pytest` also enables easy integration with other tools and plugins, such as coverage reporting and parallel test execution.

## Tests

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

### Tests Distribution

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

### Local `conftest.py`

For specialized test requirements, you can create local `conftest.py` files within test subdirectories. These local configurations:

- Override fixtures defined in the root `conftest.py`
- Define fixtures specific to tests in that directory
- Create test data relevant to the component being tested
- Allow for specialized domain configurations without affecting other tests

Local `domain.toml` files can also be created to customize domain configuration for specific test directories. The resolution order follows pytest's fixture resolution, with more specific configurations (closer to the test) taking precedence.

### Markers

Pytest markers are used to categorize tests and control their execution. Protean uses the following markers:

- `slow`: Tests that take longer to run and may be skipped during development
- `pending`: Tests that are not yet fully implemented or are waiting for a feature
- `sqlite`, `postgresql`, `elasticsearch`, `redis`, `message_db`, `sendgrid`: Tests for specific adapters
- `database`: Tests that require database interaction
- `broker_common`: Tests for message broker functionality
- `eventstore`: Tests for event store functionality
- `no_test_domain`: Tests that should not use the default test domain

These markers can be used with pytest's `-m` option to selectively run tests for a specific database, e.g., `pytest -m database --db=POSTGRESQL --ignore=tests/support/`.

Refer to `tests/conftest.py` for other database options.

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
def test_domain_initialization(test_domain):
    assert test_domain.name == "Test"
    assert test_domain.config["testing"] is True
```

### `db`

The `db` fixture handles database setup and teardown:

- Automatically associated with tests marked with `database`
- Creates all database artifacts (tables, collections, etc.) before tests
- Drops all artifacts after tests complete
- Resets the registry to ensure a clean state for subsequent tests
```

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

## Docker Containers

Protean uses Docker Compose to provide a consistent development and testing environment. The included `docker-compose.yml` file defines services for all supported adapters:

```yaml
services:
  elasticsearch:
    image: elasticsearch:8.7.0
    # configuration...

  redis:
    image: redis:7.0.11
    # configuration...
    
  postgres:
    image: postgres:15.2
    # configuration...
    
  message-db:
    image: ethangarofolo/message-db:1.2.6
    # configuration...

  ...
```

The development environment includes:
- PostgreSQL for relational database testing
- Elasticsearch for document store testing
- Redis for caching and simple key-value storage
- Message-DB for event sourcing and messaging

To start the development environment, Protean provides easy `make` commands:

```
make up
```

Refer to `Makefile` for a full list of supported `make` commands.

These containers are also used in CI pipelines to ensure consistent testing across environments.

## `protean test` Command and Options

Protean provides a built-in command for running tests:

```
protean test [OPTIONS]
```

Options:
- `-c, --category [CORE|EVENTSTORE|DATABASE|COVERAGE|FULL]`: Specifies which category of tests to run

Categories:
- `CORE`: Runs core tests without external dependencies (default)
- `EVENTSTORE`: Runs tests for all configured event store adapters
- `DATABASE`: Runs tests for all configured database adapters
- `FULL`: Runs the complete test suite with coverage

Example:
```
protean test -c DATABASE
```

This will run database tests against multiple adapters (MEMORY, POSTGRESQL, SQLITE).

### Fixtures

The `protean test` command leverages fixtures to target different adapters:

#### `db_config`

The `db_config` fixture configures database adapters based on command-line options:

- Returns configuration for MEMORY, POSTGRESQL, ELASTICSEARCH, or SQLITE
- Used to dynamically select the database to test against
- Works with the `--db` option to specify the database type

#### `store_config`

The `store_config` fixture does the same for event stores:

- Returns configuration for MEMORY or MESSAGE_DB
- Used to dynamically select the event store to test against
- Works with the `--store` option to specify the store type

## Code Coverage

<!-- Talk about coveragepy and its options in use (like coverage combine) -->

Protean uses Coverage.py to track test coverage. `coverage` configuration is maintained in `pyproject.toml`.

When running the full test suite with `protean test -c FULL`, coverage data is automatically collected and combined:

1. Each test run generates a `.coverage` file
2. The `coverage combine` command merges these files
3. The `coverage report` command generates a summary

### Constraints

Protean enforces coverage constraints to ensure code quality:

- Pull requests cannot reduce overall code coverage
- New features must have adequate test coverage
- Coverage is checked as part of the CI pipeline

If a PR introduces code that lacks sufficient test coverage:
1. The CI pipeline will fail
2. A coverage report will show which lines need tests
3. The PR author should add tests to cover the new code

To avoid coverage failures:
- Write tests alongside new code
- Test all code paths, including error cases
- Use pytest parametrization to test multiple scenarios efficiently

## Github Actions

Protean uses GitHub Actions to enforce code quality in pull requests (sample below):

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    # Test configuration...
    steps:
      # Setup steps...
      - name: Tests
        run: protean test -c FULL
        
      - name: CodeCOV
        uses: codecov/codecov-action@v4.0.1
        with:
          token: ${{ secrets.CODECOV_TOKEN }}
```

The CI pipeline:
- Runs on each pull request and push to main
- Tests against multiple Python versions (3.11, 3.12, ...)
- Sets up all required services (PostgreSQL, Redis, Elasticsearch, Message-DB, ...)
- Runs the full test suite with coverage
- Reports coverage to Codecov

Pull requests cannot be merged until tests pass. This ensures:
- All features work as expected
- No regressions are introduced
- Code coverage remains high
- Tests run on all supported Python versions

The pipeline also deploys documentation updates when changes are merged to the main branch.