# Protean — Repository Instructions

Protean is a Python framework for building domain-driven, event-sourced applications using DDD, CQRS, and Event Sourcing patterns. It uses a Ports & Adapters architecture to separate core domain logic from infrastructure.

## Build and test

```bash
# Setup
uv sync --all-extras --all-groups
pre-commit install

# Run tests (memory adapters only — no Docker needed)
protean test

# Run specific tests
uv run pytest tests/path/to/test_file.py

# Full suite with infrastructure (requires Docker services)
make up                    # Start Redis, Elasticsearch, PostgreSQL, MessageDB
protean test -c FULL       # All adapters, all tests

# Code quality
ruff check                 # Linting
ruff format                # Formatting
mypy src/protean           # Type checking
```

## Project layout

| Directory | Purpose |
|-----------|---------|
| `src/protean/core/` | Domain element base classes (aggregate, entity, value object, command, event, etc.) |
| `src/protean/domain/` | `Domain` class — the central registry and composition root |
| `src/protean/fields/` | Field system (String, Integer, HasOne, HasMany, etc.) |
| `src/protean/adapters/` | Infrastructure adapters (SQLAlchemy, Redis, Elasticsearch, MessageDB) |
| `src/protean/port/` | Port interfaces that adapters implement |
| `src/protean/server/` | Async message processing engine |
| `src/protean/cli/` | Click-based CLI (`protean test`, `protean server`, `protean check`, etc.) |
| `src/protean/utils/` | Shared utilities (outbox, processing, mixins) |
| `src/protean/ext/` | Extensions (mypy plugin) |
| `src/protean/template/` | Copier/Jinja2 templates for `protean new` |
| `tests/` | Tests organized by feature, mirroring source structure |
| `docs/` | MkDocs documentation with Material theme |
| `docs/adr/` | Architecture Decision Records |

## Python conventions

- **Python 3.11+** required. Use `X | Y` unions, `match` statements where appropriate.
- **Type hints** on all new code and any existing code touched.
- **uv** for dependency management (not Poetry). Lock file is `uv.lock`, build backend is `hatchling`.
- Follow ruff formatting and linting rules configured in `pyproject.toml`.
- **Every PR must include a `CHANGELOG.md` entry** under `[Unreleased]` using [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) sections: Added, Changed, Deprecated, Removed, Fixed, or Security.

## Breaking change policy

Every PR that touches a public API must answer: **does this break existing usage?** If yes, classify and mitigate in the same PR. See `docs/adr/0004-release-workflow-and-breaking-change-policy.md`.

- **Tier 1 (surface — renamed class, moved import, changed signature):** Introduce new API alongside old. Old API emits `DeprecationWarning` with removal version. Minimum survival: 2 minor versions.
- **Tier 2 (behavioral — same signature, different behavior):** New behavior behind a configuration flag, defaulting to old. Minimum survival: 3 minor versions.
- **Tier 3 (structural — persistence format, event schema, serialization):** Version the schema explicitly. Document migration steps. Provide migration script where feasible.

### PR checklist

1. **Identify** — does this rename, remove, or change behavior of anything in `protean.*` that user code could depend on?
2. **Classify** — Tier 1, 2, or 3?
3. **Mitigate** — apply the deprecation/flag/migration strategy in the same PR
4. **Document** — add a `CHANGELOG.md` entry (Added, Changed, Deprecated, Removed, Fixed)
5. **Test** — verify `protean check` detects deprecated usage where applicable

## Domain element patterns

All domain elements are registered via `@domain.<element>` decorators. The `Domain` class is the central registry. Key rules:

- Aggregates have a single surrogate identity — no composite keys
- Entities and Value Objects must specify `part_of` to belong to exactly one Aggregate
- Events and Commands are associated with an Aggregate via `part_of`
- Cross-aggregate references use identity fields, never direct object references
- Validation lives in the domain layer (invariants), not the database layer
- Event Sourced aggregates use `is_event_sourced=True`

## Configuration

Uses `domain.toml`, `.domain.toml`, or `pyproject.toml` with `${VAR_NAME}` environment variable substitution. Never hardcode connection strings or credentials.
