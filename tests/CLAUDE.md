# Testing Guide for Claude

Instructions for working with and writing tests in the Protean test suite.

## Environment Setup

Always use the virtual environment at `.venv` in the project root. If it
doesn't exist, create it and install dependencies:

```bash
uv sync --all-extras --all-groups
source .venv/bin/activate
```

All commands below assume this virtual environment is active.

## Running Tests

```bash
# Core tests with in-memory adapters (fast, no infrastructure needed)
protean test

# Run a specific test file or test
uv run pytest tests/aggregate/test_aggregate_initialization.py
uv run pytest tests/aggregate/test_aggregate_initialization.py::TestAggregateStructure::test_aggregate_inheritance

# By category (runs all implementations of that adapter type)
protean test -c BROKER          # All broker implementations
protean test -c DATABASE        # All database implementations
protean test -c EVENTSTORE      # All event store implementations
protean test -c FULL            # Full suite with coverage
protean test -c COVERAGE        # Full suite + diff-coverage report

# By specific technology (requires Docker services via `make up`)
uv run pytest --redis       # Redis-dependent tests
uv run pytest --postgresql  # PostgreSQL-dependent tests
uv run pytest --elasticsearch
uv run pytest --sqlite
uv run pytest --message_db
```

Add "--ignore=tests/support/" if you are running `pytest` on the entire `tests/` directory
without a specific file or directory.

## Key Principles

- **No mocks** unless truly necessary. Test against real (in-memory) adapters.
- **Check for tests with every change** and add if necessary.
- Tests in `tests/support/` are excluded from collection (`--ignore=tests/support/`).

## Test Domain Fixture

Almost every test uses the `test_domain` autouse fixture from `conftest.py`.
It creates a fresh `Domain` configured with in-memory adapters and sync
processing:

```python
def test_something(test_domain):
    test_domain.register(MyAggregate)
    test_domain.init(traverse=False)
    # ... test logic
```

To opt out (rare), mark the test with `@pytest.mark.no_test_domain`.

### Automatic Cleanup

The `run_around_tests` autouse fixture resets all provider data, broker
data, caches, and event store state after each test. You don't need to
clean up manually.

### Database Tests

Tests marked `@pytest.mark.database` automatically get the `db` fixture,
which creates and drops database artifacts around the test. The `--db`
flag selects the database: `MEMORY` (default), `POSTGRESQL`, `SQLITE`,
`MSSQL`.

## Pytest Markers

| Marker | Purpose | CLI flag to enable |
|--------|---------|-------------------|
| `@pytest.mark.slow` | Long-running tests | `--slow` |
| `@pytest.mark.pending` | Work-in-progress tests | `--pending` |
| `@pytest.mark.database` | Database adapter tests | `--database` |
| `@pytest.mark.eventstore` | Event store tests | `--eventstore` |
| `@pytest.mark.postgresql` | PostgreSQL-specific | `--postgresql` |
| `@pytest.mark.sqlite` | SQLite-specific | `--sqlite` |
| `@pytest.mark.elasticsearch` | Elasticsearch-specific | `--elasticsearch` |
| `@pytest.mark.redis` | Redis-specific | `--redis` |
| `@pytest.mark.message_db` | MessageDB-specific | `--message_db` |
| `@pytest.mark.no_test_domain` | Skip auto `test_domain` fixture | Always active |

### Broker Capability Markers

Broker tests use a capability-tier system. Higher-tier brokers run all
lower-tier tests automatically:

| Marker | Tier | Brokers |
|--------|------|---------|
| `@pytest.mark.basic_pubsub` | 1 | (none currently) |
| `@pytest.mark.simple_queuing` | 2 | Redis PubSub |
| `@pytest.mark.reliable_messaging` | 3 | Inline |
| `@pytest.mark.ordered_messaging` | 4 | Redis Streams |

## Test Structure Conventions

- **Directory per domain element**: `tests/aggregate/`, `tests/entity/`,
  `tests/event/`, etc.
- **Element definitions in `elements.py`**: Shared test domain elements live in
  `elements.py` within each test directory, not inline in test files.
- **Test classes group related assertions**: Use `class TestFeatureName:` to
  group tests. No `setUp`/`tearDown` — use fixtures.
- **Register then init**: When a test needs specific domain elements, register
  them and call `test_domain.init(traverse=False)`:

  ```python
  def test_something(test_domain):
      test_domain.register(MyAggregate)
      test_domain.register(MyCommand, part_of=MyAggregate)
      test_domain.init(traverse=False)
      # ... assertions
  ```

- **`traverse=False`**: Always pass this when calling `init()` in tests to
  prevent auto-discovery from picking up unrelated elements.

## Session-Scoped Config Fixtures

The `conftest.py` provides session-scoped fixtures that map CLI options to
adapter configurations:

- `db_config` -- Selected via `--db=MEMORY|POSTGRESQL|SQLITE|MSSQL`
- `store_config` -- Selected via `--store=MEMORY|MESSAGE_DB`
- `broker_config` -- Selected via `--broker=INLINE|REDIS|REDIS_PUBSUB`

These are injected into the `test_domain` fixture automatically.
