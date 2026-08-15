# Quality Report

Protean is built with a strong emphasis on code quality, test coverage,
and long-term maintainability. This page documents the engineering
practices and metrics behind the framework.

---

## At a Glance

| Metric | Value |
|---|---|
| **Tests** | 12,445 |
| **Test-to-Code Ratio** | 2.9:1 |
| **Linting Violations** | 0 (Ruff) |
| **Avg Cyclomatic Complexity** | 3.38 (A grade) |
| **Maintainability Index** | A rank (95% of files) |
| **Python Versions** | 3.11, 3.12, 3.13, 3.14, and the 3.15 prerelease |
| **CI Backing Services** | PostgreSQL, Redis, Elasticsearch, MessageDB, MSSQL |
| **Releases** | 46 |
| **Project Age** | Since July 2018 |
| **License** | Apache 2.0 |

---

## Test Suite

Protean has a comprehensive test suite covering domain logic, application
services, infrastructure adapters, and integration scenarios. The current
counts are in the breakdown below. This page is the single source of truth for
these numbers; other pages quote round figures and link here.

Refresh them with one command:

```bash
uv run python scripts/metrics.py
```

`tests/test_metrics_are_single_sourced.py` keeps the policy honest: it fails if
any other page states an exact count. The counts move with every PR, so they are
not pinned; what is pinned is that there is only **one place to change**.

### Test Breakdown

| Metric | Count |
|---|---|
| Total Tests | 12,445 |
| Test Functions | 12,151 |
| Test Classes | 2,737 |
| Pytest Fixtures | 1,085 |
| Parametrized Tests | 104 |

### Core vs. Integration

| Category | Tests | Share |
|---|---|---|
| Core tests (in-memory, no infrastructure) | 11,611 | 93% |
| Adapter/integration tests | 834 | 7% |

Core tests run entirely in-memory with no external dependencies, making
them fast and reliable for local development. Integration tests exercise
real databases and message brokers.

### Infrastructure Coverage

Every commit is tested against real backing services:

| Technology | Marked Tests |
|---|---|
| Database (generic) | 416 |
| Redis | 339 |
| Event Store | 280 |
| Elasticsearch | 168 |
| PostgreSQL | 85 |
| SQLite | 77 |

Branch coverage is enabled, and results are reported to
[Codecov](https://codecov.io/gh/proteanhq/protean) on every CI run.

---

## Code Quality

### Linting

Protean uses [Ruff](https://docs.astral.sh/ruff/) for both linting and
formatting. The codebase has **zero linting violations**. Pre-commit
hooks enforce this on every commit:

- `ruff check --fix` (linting with auto-fix)
- `ruff format` (consistent formatting)

### Cyclomatic Complexity

Measured with [Radon](https://radon.readthedocs.io/):

| Metric | Value |
|---|---|
| **Average complexity** | **3.38** |
| Blocks at A grade (1-5, simple) | 1,820 (84%) |
| Total blocks analyzed | 2,167 |

An average complexity under 5 indicates straightforward, easy-to-follow
code paths throughout the framework.

### Maintainability Index

| Rank | Files | Share |
|---|---|---|
| **A** (very maintainable, 20-100) | 146 | 95% |
| **B** (moderate, 10-19) | 6 | 4% |
| **C** (low, 0-9) | 1 | 1% |

**Average Maintainability Index: 63.28** (on a scale of 0-100).

95% of source files score in the highest maintainability tier.

---

## Codebase Structure

### Size

| Area | Python Files | Lines of Code | Documentation Lines |
|---|---|---|---|
| Source (`src/protean/`) | 153 | 48,347 | 5,907 |
| Tests (`tests/`) | 810 | 145,248 | 13,505 |
| **Total** | **963** | **193,595** | **19,412** |

### Architecture

Protean's source is organized into 10 top-level packages:

| Package | Purpose |
|---|---|
| `core/` | Domain elements (aggregates, entities, value objects, commands, events, handlers, services, repositories) |
| `adapters/` | Infrastructure implementations (database, broker, event store, cache) |
| `port/` | Port interfaces that adapters implement |
| `fields/` | Field system for domain element attributes |
| `domain/` | Domain class and element registration |
| `server/` | Async message processing engine |
| `cli/` | Command-line tools |
| `ext/` | Extensions (e.g., mypy plugin) |
| `utils/` | Shared utilities (outbox, eventing, mixins) |
| `template/` | Project scaffolding templates |

### Domain Elements and Adapters

| Category | Count |
|---|---|
| Domain element types | 18 (Aggregate, Entity, Value Object, Command, Event, Domain Service, Command Handler, Event Handler, Query Handler, Application Service, Subscriber, Projection, Projector, Repository, Database Model, and more) |
| Port interfaces | 5 (Provider, Broker, Event Store, Cache, DAO) |
| Adapter implementations | 12 (Memory, SQLAlchemy, Elasticsearch, Redis Stream, Redis PubSub, Inline, MessageDB, SendGrid, and more) |

---

## CI/CD Pipeline

### Test Matrix

Protean tests across five Python versions and five backing services, split
between per-PR CI and a nightly run:

- **5 Python versions**: 3.11, 3.12, 3.13, 3.14, and the 3.15 prerelease
- **5 backing services** (started as Docker containers for the adapter suite):
    - PostgreSQL 11
    - Redis
    - Elasticsearch 7.12
    - MessageDB 1.2.6
    - MSSQL Server 2022

Each pull request runs the in-memory core suite on every version and the full
adapter suite on the newest stable Python. The nightly run exercises the full
adapter suite across all five versions. This means **every change is checked on
all five Python versions, with every adapter exercised against its real backing
service**.

### Pipeline Steps

Each pull request runs these gates, all in CI so none can be bypassed by a
missing pre-commit hook, a `--no-verify`, or a web edit:

1. **Lint**: `ruff check` and `ruff format --check`, the same checks as the
   pre-commit hook.
2. **Type check**: `mypy --strict` over `src/protean`.
3. **Test suite**: the in-memory core suite (`protean test`) on every Python
   version, and the full adapter suite (`protean test -c FULL`) with all 5
   backing service containers on the newest stable Python. The nightly run
   extends the full adapter suite to every version.
4. **Coverage floor**: Overall coverage must stay at or above 94%
   (`coverage report --fail-under=94`); patch coverage is enforced separately by
   Codecov, and results are uploaded to Codecov on every run.
5. **Security scanning**: CodeQL (SAST) and a dependency-review check on any
   changed dependencies.

Documentation is deployed on merge to `main`.

### Documentation

Documentation is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
and automatically deployed to [docs.proteanhq.com](https://docs.proteanhq.com)
on every merge to `main`.

---

## Dependencies

Protean maintains a lean dependency footprint:

| Category | Count |
|---|---|
| Required runtime dependencies | 16 |
| Optional extras (adapters) | 8 groups |
| Dev dependencies | 7 |
| Test dependencies | 8 |

All database and message broker drivers are **optional extras**, the core
framework installs only what's needed for in-memory development. Infrastructure
dependencies are added when you're ready to deploy:

```bash
pip install protean[postgresql]   # Adds SQLAlchemy + psycopg2-binary
pip install protean[redis]        # Adds redis-py
pip install protean[elasticsearch] # Adds the elasticsearch client
```

---

## Project History

| Metric | Value |
|---|---|
| First commit | July 15, 2018 |
| Total commits | 1,619 |
| Commits since Jan 2024 | 647 |
| Contributors | 14 |
| Published releases | 46 |
| Current version | 0.14.2 |
| Latest releases | v0.14.0, v0.14.1, v0.14.2 |

---

## Tools and Practices

| Practice | Tool |
|---|---|
| Linting & formatting | Ruff (pre-commit + CI) |
| Type checking | mypy (with custom Protean plugin) |
| Test framework | pytest (with pytest-asyncio) |
| Coverage | coverage.py + Codecov |
| Complexity analysis | Radon |
| Dependency management | uv |
| Multi-version testing | Nox |
| CI/CD | GitHub Actions |
| Documentation | MkDocs Material |

---

*Last updated: March 2026*
