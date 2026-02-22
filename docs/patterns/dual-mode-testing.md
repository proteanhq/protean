# Dual-Mode Testing with Memory and Real Adapters

!!! tip "Quick Start"
    Already familiar with the concept? Add a `[memory]` section to your
    `domain.toml` (see [Step 1](#step-1-add-the-memory-overlay-to-domaintoml))
    and run `pytest --protean-env memory`. That's it.

## The Problem

Production Protean applications use real infrastructure -- PostgreSQL for
persistence, Redis for message brokering, Message DB for event sourcing. Tests
that run against these services provide high confidence but come with costs:

- **Docker required.** Every developer needs PostgreSQL, Redis, and Message DB
  running locally. CI jobs need service containers. A fresh contributor cannot
  run the test suite without first starting infrastructure.

- **Slow setup.** Schema creation, service health checks, and network round trips
  add seconds to every test run. A suite that takes 20 seconds with in-memory
  adapters takes 60+ seconds against real databases.

- **Flaky failures.** Network timeouts, port conflicts, and stale containers
  cause test failures unrelated to business logic. Developers learn to distrust
  test results.

These costs are worth paying for final validation, but they are too high for
the rapid feedback loops that drive development. You want to run tests after
every change, and you want them to finish in seconds.

---

## The Pattern

Run the **same test suite** in two modes:

| Mode | Adapters | When to Use |
|------|----------|-------------|
| **Memory** | In-memory database, inline broker, memory event store | Local development, pre-commit checks, CI fast lane |
| **Real** | PostgreSQL, Redis, Message DB | Final CI validation, debugging infrastructure-specific issues |

The key insight is that Protean's memory adapters implement the **same interface**
as real adapters. A test that creates an aggregate, processes a command, and
verifies a projection works identically whether the aggregate is stored in a
Python dictionary or a PostgreSQL table. By switching adapters at the
configuration level, you get two modes from one test suite with zero code changes.

```
                 ┌─────────────────┐
                 │   Test Suite    │
                 │  (unchanged)    │
                 └────────┬────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
     ┌────────▼────────┐     ┌───────▼────────┐
     │  Memory Mode    │     │   Real Mode    │
     │  (no Docker)    │     │  (with Docker) │
     │                 │     │                │
     │  memory DB      │     │  PostgreSQL    │
     │  inline broker  │     │  Redis         │
     │  memory events  │     │  Message DB    │
     └─────────────────┘     └────────────────┘
```

---

## How Protean Supports This

Protean provides three mechanisms that make dual-mode testing natural:

### 1. Memory Adapters as Defaults

Protean's default configuration uses in-memory adapters for everything:

```python
# Protean's built-in defaults
"databases": {"default": {"provider": "memory"}},
"event_store": {"provider": "memory"},
"brokers": {"default": {"provider": "inline"}},
"caches": {"default": {"provider": "memory"}},
```

These adapters implement the full provider interface -- create, read, update,
delete, filtering, sorting, stream reads, consumer groups, and data reset.
They are not stubs; they are complete implementations that happen to store
data in Python dictionaries and lists instead of external services.

### 2. Environment Overlays in `domain.toml`

The `domain.toml` configuration file supports environment-specific sections
that are deep-merged on top of the base configuration when `PROTEAN_ENV` is set:

```toml
# Base configuration (development)
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost/myapp_local"

[event_store]
provider = "message_db"
database_uri = "postgresql://localhost:5433/message_store"

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

# Test overlay: separate database, sync processing
[test]
testing = true
event_processing = "sync"

[test.databases.default]
database_uri = "postgresql://localhost/myapp_test"

# Memory overlay: all in-memory adapters
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

When `PROTEAN_ENV=memory`, the `[memory]` section is deep-merged on top of
the base configuration, replacing the adapter providers. Leftover keys like
`database_uri` and `URI` remain but are harmlessly ignored by memory adapters.

### 3. The `--protean-env` Pytest Option

Protean's pytest plugin registers a `--protean-env` CLI option (default:
`test`) that sets `PROTEAN_ENV` before test collection. Since Domain instances
read `domain.toml` at construction time, and domain modules are imported during
collection, the correct overlay is always applied:

```shell
# Real adapters (default)
pytest                            # PROTEAN_ENV=test

# Memory adapters
pytest --protean-env memory       # PROTEAN_ENV=memory
```

No test code changes. No conftest changes. No environment variables to remember.

---

## Applying the Pattern

### Step 1: Add the `[memory]` Overlay to `domain.toml`

Append to your existing `domain.toml`:

```toml
# ──────────────────────────────────────────────
# Memory overrides (PROTEAN_ENV=memory)
# Fast in-memory adapters for quick test feedback.
# No Docker, PostgreSQL, Redis, or Message DB required.
# ──────────────────────────────────────────────
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

If your application has multiple bounded contexts, add this block to each
domain's `domain.toml`. The block is identical across domains since memory
adapters need no domain-specific configuration.

### Step 2: Run Tests in Memory Mode

```shell
# All tests, in-memory
pytest --protean-env memory

# Specific test directory
pytest tests/application/ --protean-env memory

# With verbose output
pytest --protean-env memory -v
```

### Step 3: Add Convenience Targets

Add Makefile targets (or equivalent) for developer ergonomics:

```makefile
test-memory: ## Run all tests with in-memory adapters (no Docker needed)
	pytest --protean-env memory

test-memory-fast: ## Run fast tests with in-memory adapters
	pytest -m "not slow" --protean-env memory
```

### Step 4: Add a CI Fast Lane

Add a parallel CI job that runs memory-mode tests without service containers.
This job starts faster, uses fewer resources, and provides rapid feedback:

```yaml
# .github/workflows/ci.yml
test-memory:
  runs-on: ubuntu-latest
  # No services section -- no Docker needed
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install poetry && poetry install --with test
    - run: poetry run pytest --protean-env memory
```

The existing real-adapter CI job continues to run in parallel, catching
any adapter-specific issues.

---

## Multi-Domain Applications

For applications with multiple bounded contexts (each with its own `domain.toml`),
the pattern scales naturally. Each domain gets the same `[memory]` overlay:

```
src/
├── identity/
│   └── domain.toml    # [memory] overlay → memory adapters
├── catalogue/
│   └── domain.toml    # [memory] overlay → memory adapters
└── ordering/
    └── domain.toml    # [memory] overlay → memory adapters
```

Since `--protean-env memory` sets a single `PROTEAN_ENV` environment variable,
all domains pick up their respective `[memory]` overlays automatically. No
per-domain switching logic is needed.

---

## What Works Identically in Both Modes

Protean's memory adapters are complete implementations, not mocks. The
following all work identically in memory and real mode:

- **Aggregate persistence** -- create, read, update, delete via repositories
- **Query filtering** -- exact match, contains, gt/lt, in, and other lookups
- **Sorting and pagination** -- order by any field, limit/offset
- **Event sourcing** -- append events, replay from stream, snapshots
- **Event store reads** -- stream filtering, category queries, position tracking
- **Command processing** -- synchronous `domain.process()` with UoW commit
- **Event handling** -- handlers fire during UoW commit (sync mode)
- **Projections** -- projectors update read models from domain events
- **Outbox pattern** -- events written to outbox table in same transaction
- **Data reset** -- `_data_reset()` clears all state between tests

---

## When Modes May Diverge

In rare cases, tests may behave differently between modes:

- **Database-specific SQL** -- if a test relies on PostgreSQL-specific features
  (JSON operators, full-text search, advisory locks), the memory provider won't
  support it. These are infrastructure concerns, not domain logic, and should be
  isolated to integration tests.

- **Concurrent access** -- the memory provider uses thread-local locks, not
  database-level isolation. Tests that verify concurrent write behavior may
  need real adapters.

- **Message ordering** -- the inline broker provides FIFO ordering within a
  single process. Redis Streams provide ordering across distributed consumers.
  If your tests verify multi-consumer ordering, use real adapters.

The goal is for memory adapters to be functionally equivalent to real adapters
for all domain logic. If you find a case where they diverge on domain behavior,
that is a bug in the memory adapter that should be fixed.

---

## Summary

| Aspect | Memory Mode | Real Mode |
|--------|------------|-----------|
| **Command** | `pytest --protean-env memory` | `pytest` (default: `--protean-env test`) |
| **Infrastructure** | None | Docker (PostgreSQL, Redis, Message DB) |
| **Speed** | Fast (seconds) | Slower (tens of seconds) |
| **Config** | `[memory]` overlay in `domain.toml` | `[test]` overlay in `domain.toml` |
| **Test code** | Unchanged | Unchanged |
| **conftest.py** | Unchanged | Unchanged |
| **CI cost** | Low (no service containers) | Higher (service startup + health checks) |
| **Use case** | Development, pre-commit, fast CI | Final validation, infra debugging |

The pattern follows a simple principle: **your domain logic should not know or
care which adapter is active**. If it does, that is a sign that infrastructure
concerns have leaked into the domain model.

---

## See Also

- [Testing Guide](../guides/testing/index.md) -- overview of Protean's testing
  strategy, including the role of memory adapters
- [Fixtures and Patterns](../guides/testing/fixtures-and-patterns.md) -- the
  `DomainFixture` and `conftest.py` recipes that work with both modes
- [Integration Tests](../guides/testing/integration-tests.md) -- writing tests
  that exercise real infrastructure
- [Setting Up and Tearing Down Databases](setting-up-and-tearing-down-database-for-tests.md)
  -- schema and data lifecycle management for real-adapter tests
- [Configuration](../reference/configuration/index.md) -- full reference for
  `domain.toml` environment overlays
