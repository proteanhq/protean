---
applyTo: "src/**"
---

# Architecture Review Guidelines

Protean is a DDD/CQRS/Event Sourcing framework using Ports & Adapters architecture.

## Ports & Adapters boundary

- **Core domain logic** (`src/protean/core/`) must never import adapter-specific code.
- **Adapters** (`src/protean/adapters/`) implement port interfaces defined in `src/protean/port/`.
- If a feature only makes sense for one adapter (e.g., Alembic for SQLAlchemy), it belongs in the adapter, not in core.
- Schema migrations, document-style persistence, and storage-specific optimizations are adapter responsibilities.

## Domain element rules

- Aggregates have a single surrogate identity — no composite keys.
- Entities and Value Objects must belong to exactly one Aggregate (`part_of` option).
- Cross-aggregate references use identity fields, never direct object references.
- Validation and invariants live in the domain layer, not the database layer.
- Hard deletion is an infrastructure escape hatch, not a domain operation.
- Event Sourced aggregates are marked with `is_event_sourced=True`.

## Registration pattern

All domain elements are registered via `@domain.<element>` decorators. The `Domain` class is the central registry. When reviewing new elements, verify:
- The decorator is used (not manual registration)
- `part_of` is specified for non-root elements (entities, value objects, events, commands)
- Event/command handlers specify which events/commands they handle

## Configuration

Configuration uses `domain.toml`, `.domain.toml`, or `pyproject.toml` with `${VAR_NAME}` environment variable substitution. Flag any hardcoded connection strings or credentials.

## Entry points

Plugin discovery uses `[project.entry-points]` in `pyproject.toml` (PEP 621 format). Entry point group names: `protean.brokers`, `protean.providers`, `pytest11`, `mypy.plugins`.
