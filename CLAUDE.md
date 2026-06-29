# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Instructions for Claude
- Write Pythonic code with type hints; add hints to existing code you touch.
- Study similar areas of the codebase first and match established patterns. Prefer reusing existing components and utilities over adding new ones, and keep changes minimal.
- Always pass `-R proteanhq/protean` to `gh` CLI commands.
- **Changelog uses fragment files** to avoid merge conflicts. Each PR creates `changes/<issue-number>.<category>.md` (e.g., `changes/752.added.md`). When an epic completes, `/changelog #<epic>` assembles fragments into `CHANGELOG.md` under `[Unreleased]`, then deletes them. Never edit `CHANGELOG.md` directly in a feature PR. Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## Common Pitfalls

Patterns that have bitten the framework in past PRs — apply on every change touching pipelines, config, or log emissions.

- **Pipeline ordering**: when inserting a stage into an existing chain (structlog processors, middleware, filters), prepending vs appending matters. Sanitization / redaction stages run **last**, so caller-supplied stages cannot smuggle sensitive data past them. Walk the chain and confirm ordering relative to every neighbour.
- **Safety lists are additive, not substitutional**: any list-typed parameter that backstops security or correctness (`redact`, allowlists, deny-lists) must union with its defaults rather than replace them. Operators must not be able to disable a core protection by supplying their own list.
- **Negative-path tests for log emissions**: every new `protean.security`, `protean.access`, or `protean.perf` emission ships with **both** a positive test (it fires when expected) and a negative test (it does NOT fire outside its stated scope). Stated intent like "boundary-only" or "Nth-failure-only" silently drifts without one.
- **Config keys reach every entry point**: a new `domain.toml` key must be exercised through every bootstrap path the framework has — programmatic `Domain.init()`, `protean server` worker entry, `protean shell`, FastAPI middleware. A key wired in one place is a key half-wired.
- **Imports live at module top — unless there is a *verified* reason to be local.** Default to module-scope imports. A function-local (mid-code) import is only justified by one of these, and the reason should be obvious from context (or a one-line comment): (1) **optional adapter dependency** — `redis`, `sqlalchemy`, `elasticsearch`, `opentelemetry.*`, `prometheus_client`, etc., kept local so `import protean` works without the extra installed; (2) **monkeypatch test seam** — a test does `patch("source_module.symbol")` and the code must re-read it at call time, which only a local import provides (hoisting binds the real object at import time and silently breaks the patch); (3) **deliberate lazy CLI startup** — a heavy subsystem (`protean.server.*`, `protean.ir.generators.*`, observatory) pulled in by a single subcommand so `protean --help` stays fast; (4) **PEP-562 `__getattr__` lazy export**; (5) **genuine circular-import breaker**; (6) **dynamically-loaded domain module** (e.g. `from profiles import ...`). Before *hoisting* an existing local import, confirm none of the above applies — especially: grep tests for `patch("<that module>.<symbol>")`. Before *adding* a new local import, confirm one of the above applies; otherwise put it at the top. See PR #1007 for the full sweep and rationale.

## Git
- Never override `git user.name` or `git user.email` — they are already configured correctly.

## Breaking Change Policy

Every PR that touches a public API must answer: **does this break existing usage?** If yes, classify the break and apply the correct mitigation in the same PR. See ADR-0004 for the full rationale.

### Tier 1: Surface-Level Breaks (renamed class, moved import, changed signature)
- Introduce the new API alongside the old
- Old API emits `DeprecationWarning` with a specific removal version and delegates to the new implementation
- Minimum survival: **2 minor versions** (deprecated in 0.15 → earliest removal in 0.17)

```python
import warnings

def old_method(self):
    warnings.warn(
        "old_method() is deprecated. Use new_method() instead. "
        "Will be removed in v0.17.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.new_method()
```

### Tier 2: Behavioral Breaks (same signature, different behavior)
- Introduce new behavior behind a **configuration flag**, defaulting to old behavior
- Minimum survival: **3 minor versions** (opt-in → warning → default flip)
- Transition: v0.N opt-in → v0.N+1 warn if unset → v0.N+2 flip default

### Tier 3: Structural Breaks (persistence format, event schema, serialization)
- Version the schema or format explicitly
- Document exact migration steps in the release's **Upgrade Notes**
- Provide a migration script or CLI command where feasible

### Checklist for every PR
1. **Identify** — does this rename, remove, or change the behavior of anything in `protean.*` that user code could depend on?
2. **Classify** — Tier 1 (surface), Tier 2 (behavioral), or Tier 3 (structural)?
3. **Mitigate** — apply the deprecation/flag/migration strategy described above, in the same PR
4. **Document** — create a `changes/<issue>.<category>.md` fragment describing the breaking change and its deprecation path
5. **Test** — ensure `protean check` can detect the deprecated usage where applicable

## Essential Commands

```bash
uv sync --all-extras --all-groups   # Install dev dependencies
pre-commit install                  # Install pre-commit hooks

protean test                        # Core tests (in-memory adapters, no Docker)
uv run pytest <path>                # Run specific tests
make up                             # Start Redis/Elasticsearch/PostgreSQL/MessageDB
protean test -c FULL                # Full suite across adapters (needs Docker)

ruff check                          # Lint
ruff format                         # Format
mypy src/protean                    # Type check
```

CLI tools: `protean shell` (domain REPL), `protean server` (async engine), `protean observatory` (dashboard, `--domain` required), `protean new`, `protean generate`.

Full test matrix (categories `BROKER`/`DATABASE`/`EVENTSTORE`/`FULL`/`COVERAGE`, technology flags, nox multi-version): see `tests/CLAUDE.md`.

## Releasing

Protean uses **direct minor releases** cut from `main` (no release candidates); patches are cut from `release/0.X.x` branches. `bump-my-version bump minor|patch` updates the version across all tracked files and creates the commit + tag; pushing the tag triggers `.github/workflows/publish.yml`.

- Philosophy & breaking-change rationale: ADR-0004 (`docs/adr/0004-release-workflow-and-breaking-change-policy.md`).
- Step-by-step runbook (cut a minor, cut a patch, post-release checklist): `.claude/skills/release-check/reference.md`.
- Validate readiness before bumping: run `/release-check`.

## Architecture Overview

Protean is an event-driven, domain-centric framework implementing DDD, CQRS, and Event Sourcing patterns:

### Core Domain Elements
- **Aggregates**: Root entities with business logic (`@domain.aggregate`)
- **Entities**: Objects with identity (`@domain.entity`)
- **Value Objects**: Immutable descriptive objects (`@domain.value_object`)
- **Commands**: Intent to change state (`@domain.command`)
- **Events**: Things that happened (`@domain.event`)
- **Domain Service**: Encapsulate business rules/processes that span across aggregates (`@domain.domain_service`)
- **Command/Event Handlers**: Process commands/events (`@domain.command_handler`, `@domain.event_handler`)
- **Query Handlers**: Process read intents via `domain.dispatch()` (`@domain.query_handler`)
- **Application Services**: Coordinate a specific use-case (`@domain.application_service`)
- **Subscribers**: Process incoming messages from brokers (`@domain.subscriber`)
- **Projections**: Read-optimized views (`@domain.projection`)
- **Projectors**: Similar to Event handlers, but work exclusively with Projections (`@domain.projector`)
- **Repositories**: Persistence abstraction (`@domain.repository`)
- **Database Models**: Persistence technology specific data schema (`@domain.model`)

### Domain Registration
Elements are auto-discovered from domain files and registered via decorators. The `Domain` class acts as a central registry with type-safe element resolution.

### Domain Element Options
A domain element's behavior can be customized by passing additional options to its decorator.

### Adapter Architecture
Port/Adapter pattern separates core domain from infrastructure:

**Ports** (interfaces):
- `BaseProvider`: Database connections
- `BaseBroker`: Message brokers
- `BaseEventStore`: Event storage
- `BaseCache`: Cache

**Adapters** (implementations):
- **Repositories**: Memory, SQLAlchemy, Elasticsearch
- **Brokers**: Inline, Redis (Stream/PubSub)
- **Event Stores**: Memory, MessageDB
- **Caches**: Memory, Redis

### Server/Engine
Async message processing with:
- `EventStoreSubscription`: Domain events/commands
- `BrokerSubscription`: External messages
- `StreamSubscription`: Priority-aware Redis Stream polling (primary + backfill lanes)
- Graceful lifecycle management
- Test mode for deterministic testing

### Key Patterns
- **Outbox Pattern**: Reliable message delivery with `src/protean/utils/outbox.py`
- **Priority Lanes**: Two-lane event routing (`src/protean/utils/processing.py`) — production events flow through the primary stream while bulk/migration events are routed to a backfill stream, configured via `server.priority_lanes`
- **Unit of Work**: Automatic transaction management
- **Global Context**: Thread-local access via `current_domain`, `current_uow`
- **Fact Events**: Auto-generated from aggregate changes

## Configuration

Uses `domain.toml`, `.domain.toml`, or `pyproject.toml` with environment variable substitution (`${VAR_NAME}`).

## Testing Strategy

- Avoid mocks unless necessary
- Use pytest markers: `@pytest.mark.database`, `@pytest.mark.broker`, etc.
- Test all adapter implementations with configuration flags
- Capability-based broker testing with tier system

### Marker-Based Test Selection

Test selection is **purely marker-based** — never directory or file-path based.

- **`protean test`** (CORE): Runs all unmarked tests with in-memory adapters. No external services needed.
- **`protean test -c FULL`**: Starts external services via Docker and passes adapter-specific CLI flags (`--redis`, `--postgresql`, etc.) to enable marked tests.

Every test that requires an external service (PostgreSQL, Redis, Elasticsearch, MessageDB, etc.) **must** carry the corresponding pytest marker. Tests that use in-memory exporters or mocks for the external side (e.g., OpenTelemetry with `InMemorySpanExporter`) are core tests and need no marker.

Optional adapter packages (`sqlalchemy`, `redis`, `elasticsearch`, `opentelemetry`, etc.) live under `[project.optional-dependencies]` in `pyproject.toml` and are expected to be installed in dev environments via `uv sync --all-extras --all-groups`.

### Test Placement

Tests are organized by feature into directories under `tests/`. Always place new tests in the directory that matches the source code being tested — never create monolithic test files that mix unrelated concerns.

| Source location | Test location |
|-----------------|---------------|
| `src/protean/cli/` | `tests/cli/` (e.g. `test_db.py`, `test_server.py`) |
| `src/protean/domain/` | `tests/domain/` (e.g. `test_database_lifecycle.py`, `test_domain_config.py`) |
| `src/protean/server/` | `tests/server/` (e.g. `test_engine_initialization.py`) |
| `src/protean/adapters/` | `tests/adapters/` (organized by adapter type) |
| `src/protean/integrations/pytest/` | `tests/integrations/pytest/` |
| `src/protean/core/<element>.py` | `tests/<element>/` (e.g. `tests/aggregate/`, `tests/entity/`) |
| `src/protean/utils/` | `tests/utils/` |

When a test creates its own `Domain(name="Test")` instead of using the autouse `test_domain` fixture, mark it with `@pytest.mark.no_test_domain` so the fixture is skipped.

## Important File Locations

- **Core Domain Logic**: `src/protean/core/`
- **Adapters**: `src/protean/adapters/`
- **Ports**: `src/protean/port/`
- **CLI**: `src/protean/cli/`
- **Server Engine**: `src/protean/server/`
- **Field System**: `src/protean/fields/`
- **Utils**: `src/protean/utils/`
- **Tests**: `tests/` (organized by feature)

## Mypy Plugin Development

The mypy plugin at `src/protean/ext/mypy_plugin.py` provides two hooks:

- **`get_function_hook`** — Overrides field factory return types (`String()` → `str`)
- **`get_customize_class_mro_hook`** — Injects base classes for decorator-registered classes

### Testing the plugin
```bash
uv run pytest tests/ext/ -v                    # All plugin tests
uv run pytest tests/ext/test_mypy_plugin.py -v  # Integration tests (runs mypy)
uv run pytest tests/ext/test_mypy_plugin_unit.py -v  # Unit tests
```

### Debug mode
Set `PROTEAN_MYPY_DEBUG=1` to print diagnostic info about decorator matching and base class injection to stderr.

### Fixture conventions
- Field fixtures: `tests/ext/fixtures/` (e.g. `simple_fields.py`, `optional_fields.py`)
- Decorator fixtures: `tests/ext/fixtures/` (e.g. `decorator_aggregate.py`, `decorator_entity.py`)
- Each fixture uses `reveal_type()` calls with expected type comments
- Ruff ignores `F821` for all fixture files via `pyproject.toml`

### Key design decisions
- `get_class_decorator_hook` cannot be used because `@dataclass_transform()` on Domain methods causes mypy to bypass it
- `get_customize_class_mro_hook` is used instead — it fires for every class during MRO calculation
- Base class symbols are copied into the class namespace (not added to `info.bases`) to avoid metaclass conflicts with pydantic

## Design Philosophy

Protean is an opinionated DDD framework that guides users toward correct patterns, not a toolkit that accommodates every possible feature. When evaluating changes, apply this filter:

- **Domain concerns belong in the framework; infrastructure concerns belong in adapters.** Schema migrations, document-style persistence, and storage-specific optimizations are adapter responsibilities, not framework responsibilities. Protean defines port contracts; adapters own their infrastructure.
- **DDD purity over convenience.** Aggregates have single surrogate identities (no composite keys). Validation lives in the domain layer (invariants), not the database layer. Hard deletion is an infrastructure escape hatch, not a domain operation.
- **Don't abstract over technology-specific concerns.** If a feature only makes sense for one adapter (e.g., Alembic for SQLAlchemy), it doesn't belong in core Protean. The Ports & Adapters pattern exists precisely to keep these concerns separate.
- **Code excellence over feature breadth.** Prefer fixing inconsistencies, unifying patterns, and improving type safety over adding new capabilities. A smaller, coherent framework is better than a large, sprawling one.

## Roadmap

Check `todo/0-ROADMAP.md` for current roadmap state before starting work on any epic or feature. Update it when epic status changes (Backlog → Active → In Progress → Done).

## Epic Planning Workflow

Epics are planned and broken into PR-sized GitHub sub-issues via the `/epic-plan` skill. The durable trail is commits, PRs, and issues — not the project board, which gets archived.

- **Single layer**: all tracking is real GitHub Issues. Epic = issue labeled `epic` (Item Type = Epic), converted from its pre-populated draft item on Project #15; each sub-issue = one PR (Item Type = Task), linked as a native sub-issue with the same Capability as the parent. No draft issues or `N.M.x` numbering.
- **One issue = one PR**; tests ship with the code in the same PR, never separately.
- PRs reference "Closes #N"; dependencies use GitHub's "Blocked by"/"Blocks" relationships.
- Update `todo/0-ROADMAP.md` when epic status changes (mark previous Done, new Active).
- Full phase-by-phase workflow, board automation, and the GitHub Project GraphQL/field-ID reference live with the skill: `.claude/skills/epic-plan/SKILL.md` and `.claude/skills/epic-plan/reference.md`.

## Skills

This repo ships Claude Code skills under `.claude/skills/` (e.g. `/implement`, `/pr`, `/check`, `/epic-plan`). For the full catalogue — what each does, when *not* to reach for it, and how they compose — see `.claude/skills/INDEX.md`.

## Architecture Decision Records (ADRs)

Architectural decisions are recorded in `docs/adr/`. When a discussion leads to a design decision — whether during a PR review, a planning session, or an implementation spike — create an ADR for it. The ADR should ideally be included in the same PR as the implementation it documents. See `docs/adr/README.md` for the naming convention and template.

## Development Notes

- Main branch: `main`
- Use uv for dependency management
- Pre-commit hooks enforce code quality
- Support Python 3.11+
- Framework follows Domain-Driven Design principles
- Event-driven architecture with async processing
- Allows two architecture flavors of applications: CQRS and EventSourcing
- Aggregates will be marked with `is_event_sourced=True` option if EventSourced
- Comprehensive test coverage required
