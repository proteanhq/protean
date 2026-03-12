# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Instructions for Claude
- Always suggest Pythonic code
- Add Typehints to new code, or existing code when touched
- Think harder and thoroughly examine similar areas of the codebase to ensure your proposed approach fits seamlessly with the established patterns and architecture.
- Aim to make only minimal and necessary changes, avoiding any disruption to the eisting design.
- Whenever possible, take advantage of components, utilities, or logic that have already been implemented to maintain consistency, reduce duplication, and streamline integration with the current system.
- Always use the `-R proteanhq/protean` flag with `gh` CLI commands to explicitly target the correct repository.


## Essential Commands

### Development Setup
```bash
# Install development dependencies
uv sync --all-extras --all-groups

# Install pre-commit hooks
pre-commit install
```

### Testing
```bash
# Basic tests with memory adapters
protean test

# Run specific test configurations
protean test -c BROKER      # Test all broker implementations
protean test -c DATABASE    # Test all database implementations
protean test -c EVENTSTORE  # Test all event store implementations
protean test -c FULL        # Full test suite with coverage
protean test -c COVERAGE    # Coverage report

# Test with specific technologies
protean test --redis --postgresql --elasticsearch --sqlite

# Run specific tests with pytest
uv run pytest <individual tests or test files>

# Multi-version testing with nox (requires pyenv with 3.11, 3.12, 3.13, 3.14)
make test-matrix           # Core tests across all Python versions
make test-matrix-full      # Full suite across all Python versions (starts Docker services)
uv run nox -s tests-3.13   # Core tests on a specific version
```

### Docker Services
```bash
make up    # Start Redis, Elasticsearch, PostgreSQL, MessageDB
make down  # Stop services
```

### CLI Tools
```bash
protean shell       # Interactive shell with domain context
protean server      # Run async message processing engine
protean observatory # Run observability dashboard (--domain required)
protean new         # Create new projects
protean generate    # Generate docker-compose files
```

### Code Quality
```bash
ruff check          # Linting
ruff format         # Formatting
mypy src/protean    # Type checking
```

### Releasing

See ADR-0004 (`docs/adr/0004-release-workflow-and-breaking-change-policy.md`) for the full release philosophy.

#### Version bump commands

```bash
# Install bump-my-version (in dev dependencies)
uv sync --group dev

# Release candidate (e.g., 0.14.2 → 0.15.0rc1)
bump-my-version bump minor          # Bumps minor and sets rc1

# Next RC (e.g., 0.15.0rc1 → 0.15.0rc2)
bump-my-version bump rc

# Final release (e.g., 0.15.0rc2 → 0.15.0)
bump-my-version bump rc             # rc goes from last value to "final", dropping the rc suffix

# Patch release (e.g., 0.15.0 → 0.15.1)
bump-my-version bump patch
```

Version is updated automatically in: `pyproject.toml`, `src/protean/__init__.py`, `src/protean/template/domain_template/pyproject.toml.jinja`, `docs/guides/getting-started/installation.md`.

`bump-my-version` auto-creates a commit and tag (e.g., `v0.15.0rc1`). Push the tag to trigger the publish workflow.

The GitHub Actions workflow (`.github/workflows/publish.yml`) handles:
- Building with uv
- Publishing to PyPI (trusted publishing)
- Creating a GitHub Release (marked as pre-release for RC tags)

#### Release branch workflow

When an RC is tagged, a release branch is created from that tag. Development continues on `main`; RC bugfixes are cherry-picked to the release branch.

```
main:              ──A──B──[tag rc1]──D──E(R2 work)──F──...
                             │
release/0.15.x:              └──cherry-pick(fix)──[tag rc2]──[tag v0.15.0]
```

**Starting an RC:**
```bash
# On main: bump version and tag
bump-my-version bump minor                    # 0.14.2 → 0.15.0rc1
git push origin main --tags

# Create release branch from the RC tag
git branch release/0.15.x v0.15.0rc1
git push origin release/0.15.x
```

**Fixing an RC bug:**
```bash
# Fix the bug on main first (or on the release branch if main-only is impractical)
# Then cherry-pick to the release branch:
git checkout release/0.15.x
git cherry-pick <commit-hash>
bump-my-version bump rc                      # 0.15.0rc1 → 0.15.0rc2
git push origin release/0.15.x --tags
```

**Cutting the final release:**
```bash
git checkout release/0.15.x
bump-my-version bump rc                      # 0.15.0rcN → 0.15.0
git push origin release/0.15.x --tags
```

**Hotfix after final:**
```bash
git checkout release/0.15.x
git cherry-pick <fix-commit>
bump-my-version bump patch                   # 0.15.0 → 0.15.1
git push origin release/0.15.x --tags
```

**Post-release checklist:**
1. Add a new `X.Y.0 (unreleased)` section to `CHANGELOG.rst` on `main`
2. Verify the package on PyPI

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

When planning and executing an epic, follow this structured workflow. The goal is to produce a durable historical trail in commits, PRs, and issues.

### Phase 1: Deep-Dive and Issue Breakdown

1. **Review the epic** on the GitHub Project (private, `github.com/orgs/proteanhq/projects/15`) and the roadmap (`todo/0-ROADMAP.md`).
2. **Deep-dive into the codebase** — understand what exists, what's missing, what patterns to follow.
3. **Break down into sub-issues** — each sub-issue is a coherent, PR-sized unit of work. Tests ship with the code they test.

### Phase 2: Create Tracking Artifacts

Single layer — all tracking uses **real GitHub Issues**:

- **Epic issue** — labeled `epic`, added to the project board with Item Type = Epic. Sub-issues are linked using GitHub's native sub-issues feature for automatic progress tracking.
- **Sub-issues** — real GitHub Issues linked as native sub-issues of the epic. Each sub-issue = one PR. Added to the project board with Item Type = Task.
- PR descriptions reference "Closes #N" to create permanent cross-references.
- Use GitHub's **issue relationships** ("Blocked by" / "Blocks") for dependencies between sub-issues.

No draft issues or internal numbering schemes (N.M.x). Everything is public and self-contained.

### Phase 3: Update Roadmap

- Update `todo/0-ROADMAP.md`: mark previous epic Done, new epic Active
- Update the Active Work section with current focus, plan file path, and issue count

### Phase 4: Execute

- Work through sub-issues sequentially for deep context
- Each PR closes its corresponding sub-issue
- Run full test suite before each PR

### Key Principles

- **Commits and PRs are the durable artifacts** — project boards get archived, but PR descriptions, commit messages, and review threads are the permanent trail
- **One issue = one PR** — every sub-issue maps to exactly one PR
- **Tests ship with code** — never as a separate PR; each PR is independently verifiable

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
