# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Instructions for Claude
- Always suggest Pythonic code
- Add Typehints to new code, or existing code when touched
- Think harder and thoroughly examine similar areas of the codebase to ensure your proposed approach fits seamlessly with the established patterns and architecture.
- Aim to make only minimal and necessary changes, avoiding any disruption to the eisting design.
- Whenever possible, take advantage of components, utilities, or logic that have already been implemented to maintain consistency, reduce duplication, and streamline integration with the current system.
- Always use the `-R proteanhq/protean` flag with `gh` CLI commands to explicitly target the correct repository.
- **Changelog uses fragment files** to avoid merge conflicts. Each PR creates a file in `changes/<issue-number>.<category>.md` (e.g., `changes/752.added.md`). When an epic completes, `/changelog #<epic>` assembles fragments into `CHANGELOG.md` under `[Unreleased]` as a per-epic section, then deletes the fragments. Never edit `CHANGELOG.md` directly in a feature PR. The changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.

## Common Pitfalls

Patterns that have bitten the framework in past PRs — apply on every change touching pipelines, config, or log emissions.

- **Pipeline ordering**: when inserting a stage into an existing chain (structlog processors, middleware, filters), prepending vs appending matters. Sanitization / redaction stages run **last**, so caller-supplied stages cannot smuggle sensitive data past them. Walk the chain and confirm ordering relative to every neighbour.
- **Safety lists are additive, not substitutional**: any list-typed parameter that backstops security or correctness (`redact`, allowlists, deny-lists) must union with its defaults rather than replace them. Operators must not be able to disable a core protection by supplying their own list.
- **Negative-path tests for log emissions**: every new `protean.security`, `protean.access`, or `protean.perf` emission ships with **both** a positive test (it fires when expected) and a negative test (it does NOT fire outside its stated scope). Stated intent like "boundary-only" or "Nth-failure-only" silently drifts without one.
- **Config keys reach every entry point**: a new `domain.toml` key must be exercised through every bootstrap path the framework has — programmatic `Domain.init()`, `protean server` worker entry, `protean shell`, FastAPI middleware. A key wired in one place is a key half-wired.

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

Protean uses **direct minor releases** (no release candidates). Minor versions are cut straight from `main` when the changelog has substantive entries. Bugs discovered after a release are shipped as **patch releases** from the release branch.

#### Version bump commands

```bash
# Install bump-my-version (in dev dependencies)
uv sync --group dev

# Minor release (e.g., 0.15.0 → 0.16.0)
bump-my-version bump minor

# Patch release (e.g., 0.15.0 → 0.15.1)
bump-my-version bump patch
```

Version is updated automatically in: `pyproject.toml`, `src/protean/__init__.py`, `src/protean/template/domain_template/pyproject.toml.jinja`, `docs/guides/getting-started/installation.md`, `.bumpversion.toml`.

`bump-my-version` auto-creates a commit and tag (e.g., `v0.16.0`). Push the tag to trigger the publish workflow.

The GitHub Actions workflow (`.github/workflows/publish.yml`) handles:
- Building with uv
- Publishing to PyPI (trusted publishing)
- Creating a GitHub Release

#### Minor release workflow (from main)

```
main:  ──A──B──C──[tag v0.16.0]──D──E──...
                      │
release/0.16.x:       └── (created on demand for patches)
```

**Cutting a minor release:**

```bash
git checkout main
git pull --ff-only

# 1. Finalize CHANGELOG: rename [Unreleased] → [0.X.0] - YYYY-MM-DD, leave a fresh empty [Unreleased] above it
$EDITOR CHANGELOG.md
git add CHANGELOG.md
git commit -m "Mark 0.X.0 release in CHANGELOG"

# 2. Bump version, create commit + tag
bump-my-version bump minor                    # 0.15.0 → 0.16.0
git push origin main --tags

# 3. Create release branch from the new tag (for future patches)
git branch release/0.16.x v0.16.0
git push origin release/0.16.x
```

#### Patch release workflow (from release branch)

Bugfixes land on `main` first, then are cherry-picked to the release branch:

```bash
# Fix the bug on main, merge PR, then:
git checkout release/0.16.x
git pull --ff-only
git cherry-pick <commit-hash>

# Update CHANGELOG on the release branch under [0.16.1]
$EDITOR CHANGELOG.md
git add CHANGELOG.md
git commit -m "Mark 0.16.1 release in CHANGELOG"

bump-my-version bump patch                    # 0.16.0 → 0.16.1
git push origin release/0.16.x --tags
```

**Post-release checklist:**
1. Verify the `[Unreleased]` section in `CHANGELOG.md` on `main` is empty and ready for the next cycle
2. Verify the package on PyPI
3. For minor releases, confirm `release/0.X.x` branch is pushed for future patches

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

When planning and executing an epic, follow this structured workflow. The goal is to produce a durable historical trail in commits, PRs, and issues.

### Phase 1: Deep-Dive and Issue Breakdown

1. **Review the epic** on the GitHub Project (private, `github.com/orgs/proteanhq/projects/15`) and the roadmap (`todo/0-ROADMAP.md`).
2. **Deep-dive into the codebase** — understand what exists, what's missing, what patterns to follow.
3. **Break down into sub-issues** — each sub-issue is a coherent, PR-sized unit of work. Tests ship with the code they test. Avoid mocks. Aim for 100% coverage.

### Phase 2: Create Tracking Artifacts

Single layer — all tracking uses **real GitHub Issues**:

- **Epic issue** — Every epic already exists as a **draft item** in the GitHub Project with its Sequence, Release, Requires, and Item Type fields pre-populated. **Do not create a new issue.** Instead, convert the existing draft item to a real issue:
  1. Open the draft item in the project board
  2. Click the item title → select **"Convert to issue"** → choose the `proteanhq/protean` repository
  3. Add the `epic` label and flesh out the body with outcome, why, and success criteria
  4. The project fields (Sequence, Release, Requires, Status, Item Type) are preserved automatically
- **Sub-issues** — real GitHub Issues linked as native sub-issues of the epic. Each sub-issue = one PR. Added to the project board with Item Type = Task and the same Release field as the parent epic.
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

### GitHub Project API Reference

Useful GraphQL mutations and queries for project management tasks. Project ID: `PVT_kwDOAmXm_s4BRFMC`.

**Convert a draft item to a real issue** (preserves all project fields):
```
mutation { convertProjectV2DraftIssueItemToIssue(input: {
  projectId: "PVT_kwDOAmXm_s4BRFMC"
  itemId: "<draft-item-id>"
  repositoryId: "<repo-node-id>"
}) { item { id } } }
```

**Set a field value on a project item** (works for Status, Release, Sequence, Requires, Item Type):
```
mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "PVT_kwDOAmXm_s4BRFMC"
  itemId: "<item-id>"
  fieldId: "<field-id>"
  value: { singleSelectOptionId: "<option-id>" }  # or: { text: "..." } / { number: N }
}) { projectV2Item { id } } }
```

**Add a blocked-by relationship between two real issues** (`issueId` is the blocked one):
```
mutation { addBlockedBy(input: {
  issueId: "<blocked-issue-node-id>"
  blockingIssueId: "<blocking-issue-node-id>"
}) { issue { number } blockingIssue { number } } }
```
Returns "already taken" validation error if the relationship already exists — safe to treat as a no-op.

**Query blocked-by/blocking on an issue:**
```
{ repository(owner: "proteanhq", name: "protean") {
  issue(number: N) {
    blockedBy(first: 10) { nodes { number title } }
    blocking(first: 10) { nodes { number title } }
  }
} }
```

**Key field IDs** (project #15):

| Field | ID | Notes |
|-------|----|-------|
| Status | `PVTSSF_lADOAmXm_s4BRFMCzg_A5gY` | Backlog=`f75ad846`, Active=`5a1d9210`, In Progress=`47fc9ee4`, Done=`98236657` |
| Item Type | `PVTSSF_lADOAmXm_s4BRFMCzg_KRSg` | Epic=`1acf4758`, Task=`ae8e6519` |
| Release | `PVTSSF_lADOAmXm_s4BRFMCzg_A5uY` | R1=`10eabad0`, R2=`38bb22fc`, R3=`821b3922` |
| Sequence | `PVTF_lADOAmXm_s4BRFMCzg_kOnU` | Number field (1–37 global execution order) |
| Requires | `PVTF_lADOAmXm_s4BRFMCzg_kQTc` | Text field, e.g. `"1.1, 1.6"` |

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
