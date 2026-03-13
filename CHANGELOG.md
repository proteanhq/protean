# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- JSON Schema generator (`protean.ir.generators.schema`) — pure functions that
  convert IR element dicts into standard JSON Schema (Draft 2020-12) with
  `x-protean-*` extension metadata for all data-carrying domain elements
- Schema file writer (`protean.ir.generators.schema_writer`) — materializes
  generated JSON Schemas to a `.protean/schemas/` directory tree with
  cluster-aware grouping by aggregate, versioned filenames, and deterministic
  output
- `protean schema generate` CLI command — generates JSON Schema files for all
  data-carrying elements from a live domain (`--domain`) or IR file (`--ir`),
  writing to `.protean/schemas/` by default with configurable `--output`
- `protean schema show` CLI command — displays the JSON Schema for a specific
  element by name or FQN, with syntax-highlighted output (default) or raw JSON
  (`--raw`) for piping
- Meta-schema validation tests — all generated schemas validated against JSON
  Schema Draft 2020-12 meta-schema
- End-to-end payload validation tests — sample payloads validated against
  generated schemas
- ADR-0005: IR-first schema generation rationale
- ADR-0006: Standard JSON Schema with `x-protean-*` extensions rationale
- Schema generation user guide (`docs/guides/compose-a-domain/schema-generation.md`)

## [0.15.0rc1] - 2026-03-11

### Added

- **Pydantic v2** as the validation and serialization engine — all domain
  elements inherit from Pydantic's `BaseModel` with Rust-powered validation
- Three field definition styles: annotation (recommended), assignment
  (backward-compatible), and raw Pydantic (escape hatch)
- `FieldSpec` abstraction — Protean's field functions (`String`, `Integer`,
  etc.) return `FieldSpec` objects resolved into Pydantic `Annotated[type,
  Field(...)]` at class creation time
- JSON Schema generation via `model_json_schema()` on all domain elements
- Native serialization via `model_dump()` and `model_dump_json()`
- mypy plugin (`protean.ext.mypy_plugin`) resolving FieldSpec return types to
  Python types (`String` → `str`, `Integer` → `int`, etc.)
- `py.typed` marker for PEP 561 compliance
- `pyrightconfig.json` to suppress `reportInvalidTypeForm` for
  annotation-style fields
- `ValueObjectList` field for embedding Value Object lists (replaces old `List`
  descriptor behavior)
- Outbox pattern for reliable message delivery — events persisted in the same
  transaction as aggregate changes, delivered by `OutboxProcessor`
- Message format versioning with `specversion`, `checksum`, and
  `MessageHeaders`
- Redis Streams for async event/command processing
- Broker registry for runtime broker discovery and management
- Subscription configuration system with priority hierarchy
- Command idempotency with Redis-backed deduplication
- Intermediate Representation (IR) — `domain.to_ir()` captures complete domain
  topology as JSON
- `protean check` CLI — validates domain definitions and reports errors,
  warnings, and diagnostics with severity levels
- Architecture documentation generation — `protean docs generate` produces
  Mermaid diagrams for aggregate clusters, event flows, handler wiring, and
  event catalogs
- IR metadata enrichment — contracts with language-neutral keys, version, and
  field schemas; description and repository database in IR output
- IR diff engine — `protean ir diff` detects breaking changes between IR
  snapshots
- Testing DSL — `protean.testing` module with `given()`, `EventSequence`,
  `ProjectionResult`, `ProcessManagerSetup`, `ProcessManagerResult`
- Snapshot testing — JSON snapshot files with `assert_snapshot()` and
  `--update-snapshots` pytest flag
- `assert_invalid()` and `assert_valid()` assertion helpers
- Process managers — `@domain.process_manager` for multi-aggregate process
  coordination with state transitions
- Query handlers — `@domain.query_handler` and `domain.dispatch()` for
  read-side CQRS
- First-class `@domain.query` element for read-side CQRS
- `ReadView` via `domain.view_for()` for read-only projection access
- `ReadOnlyQuerySet` via `domain.query_for()` for CQRS read-side queries
- ValueObject support in Projections
- Status field with state transition enforcement
- Event upcasters — `@domain.upcaster` for transparent event schema evolution
- Priority lanes — two-lane event routing through Redis Streams (primary +
  backfill)
- Multi-worker supervisor for the Protean Engine
- Observatory dashboard — `protean observatory` for real-time domain monitoring
- Dead letter queue management — inspect, replay, and purge failed messages
- Subscription lag monitoring via Observatory, Prometheus, and CLI
- Database lifecycle API — `domain.create_database()`,
  `domain.drop_database()`, `domain.truncate_database()` with CLI commands
- Database capability system — `DatabaseCapabilities` enum with
  capability-based pytest markers
- Entry-points adapter discovery — provider registry migrated from hardcoded
  dict to `entry_points`
- Adapter conformance testing — `protean test-adapter` CLI with generic test
  suites
- Structured logging with `structlog` integration
- FastAPI middleware for `DomainContext` propagation
- Correlation and causation IDs — end-to-end message tracing
- Causation chain API for traversing command/event causal relationships
- Message enrichment hooks for events and commands
- Event store inspection CLI — read, stats, search, history
- Temporal queries for event-sourced aggregates
- Projection rebuilding — CLI command and domain API
- Manual snapshot triggers for event-sourced aggregates
- Python 3.14 support; multi-version testing via `nox`
- pytest plugin — `DomainFixture` and auto-env configuration
- Enhanced domain linting with unified diagnostic model and severity levels
- `protean shell` interactive shell with domain context
- CloudEvents v1.0 serialization as boundary contract
- Multi-tenancy documentation and context propagation pattern
- ADR practice established in `docs/adr/`
- Documentation: defining fields guide, field system internals, migration guide
  for 0.12–0.14 → 0.15, quickstart, long-form tutorial (Online Bookstore),
  testing guide, application services guide, subscribers guide, patterns &
  recipes, and landing page revamp

### Changed

- `List` field is now a `FieldSpec` factory for generic typed lists (use
  `ValueObjectList` for the old Value Object list descriptor)
- Event/command `__version__` is now an integer, not a string
- Metadata attributes restructured across commands and events; `message.py`
  folded into `eventing.py`
- `DeserializationError` introduced for enhanced error handling context
- Domain class refactored into 7 focused helper classes using composition
- Async message processing improvements and Engine lifecycle hardening
- Invariants checked only when there are no field-level errors

### Deprecated

- `from protean.fields import List` as Value Object list descriptor — use
  `ValueObjectList` instead

### Removed

- `MessageRecord` — metadata attributes restructured
- `update_all` and `delete_all` from `QuerySet` public API

### Fixed

- Mark aggregate dirty when ValueObject field is updated
- Rebind `__class__` cells in `derive_element_class`
- Sorting by `referenced_as` attributes

## [0.14.2] - 2025-08-24

### Added

- `via` parameter support on Reference and Association fields

### Changed

- Entity and model conversion methods refactored to use `referenced_as`
  attributes
- Documentation on entity relationships, per-aggregate CQRS/ES pattern choice,
  and deciding between aggregates and entities

## [0.14.1] - 2025-08-14

### Added

- Schema support in MSSQL connection string

## [0.14.0] - 2025-08-13

### Added

- Microsoft SQL Server support
- Python 3.13 support
- Outbox processor for reliable message delivery
- `has_table` inspection method on all DAO implementations

## [0.13.1] - 2025-06-03

### Fixed

- Keep server running by gracefully logging exceptions

## [0.13.0] - 2025-03-09

### Added

- Multi-environment configuration support (dev, staging, prod) driven by TOML
- `Field.clone()` helper for programmatically copying field definitions

### Changed

- Major event-sourcing overhaul — unified event-sourced and regular Aggregates,
  making them interchangeable in client code
- Stream subsystem refinements reducing boilerplate and improving performance
- Domain initialized before the Engine starts; explicit check for compatible
  database provider at initialization
- Simplified Broker and Subscriber APIs; subscribers now run inside the Engine
  event loop
- Exceptions hierarchy streamlined
- `Options` refactored to subclass `dict` for easier introspection
- Application-service enhancements: stricter invariants and clearer lifecycle
  hooks

## [0.12.1] - 2024-06-20

### Added

- Constants under `[custom]` section available directly on the domain

### Changed

- Simplified domain traversal logic with improved performance
- Optimized handler fetching for domain events

### Removed

- `clone` method from Entity/Aggregate
- `provider` meta option from Entities

## [0.12.0] - 2024-06-17

### Added

- `protean shell` CLI command
- Support for different identity types in `Identifier` field
- Specifying child entities during Aggregate initialization
- Nesting of associations
- `@invariant` decorator — runs on initialization and attribute changes
- Domain config in TOML with environment variable support
- Domain Service enhancements with `pre` and `post` invariant structures
- Filtering on `HasMany` entities
- Lists as field value choices along with Enums
- Custom identity function support
- Identity generation customization in Auto field
- Publishing multiple events in a single call

### Changed

- Switched from Copier to Typer for project generation with comprehensive tests
- Switched docs to Material for MkDocs (https://docs.proteanhq.com)
- Domain name initialized to domain's module name when not provided
- CLI module refactoring for Typer
- Commands and Events are now immutable
- Replaced `flake8` + `black` + `isort` with `ruff`
- Identity generated as first step during entity initialization
- Auto-add reference fields in child entities
- Associations can only link to other entities
- References resolved when initializing Domain
- `aggregate_cls` renamed to `part_of`
- Owner and root linkages preserved in child entities
- `Entity.defaults` runs before validations
- SQLAlchemy upgraded to 2.0.x
- BaseModel revamped for parity with other domain elements
- Events registered only on Aggregates
- Aggregate cluster tracked for element membership
- Naked `Repository.add` calls enclosed within UoW

### Removed

- Support for inner Meta class
- `all` method from repository
- `current_domain` usage where domain is readily accessible
- `via` param for associations (re-added in 0.14.2)

## [0.11.0] - 2024-03-16

### Added

- Python 3.12 support

### Changed

- Moved to Poetry for dependency management
- Domain directory traversal controlled explicitly in `init()`
- Domain traversal refactoring

## [0.10.0] - 2023-11-16

### Changed

- `domain.init` enhanced as the way to activate a domain
- Introduced `WITH_COVERAGE` test category for GitHub Actions

### Removed

- Dynamic initializations in providers, brokers, caches, and event stores

## [0.9.1] - 2022-02-23

### Fixed

- Use Domain's EventStore connection details for clearing events after test
  runs

## [0.9.0] - 2022-02-17

### Added

- MessageDB Event store adapter
- Memory Event store (stand-in)
- EventSourced Aggregates and Event Handlers
- EventSourced Repositories
- Filtering messages from their origin stream
- Event Handlers can listen to other streams and ALL streams
- Command Handler methods can handle any event
- Synchronous event and command processing mode
- Asynchronous command processing by submitting commands to domain
- `autoflake` added to pre-commit
- `any` filter and scalar values for `in` operator in Memory DB
- Support for inter-attribute dependencies in Option defaults
- Caching for registry, repositories, DAOs, and models via `@cache`

### Changed

- Value Object values output as nested dicts instead of forced flat structure
- DAOs enclosed within repositories — DB interaction solely through repos
- Aggregate versions for concurrency management
- EventHandler and CommandHandler methods execute within UnitOfWork
- Commands and Events associated with streams (explicit and via Aggregates)
- Empty string treated as None in Date and DateTime Fields

### Removed

- `remove` method from repository (to discourage hard deletes)

### Fixed

- Sorting issue with null values in Memory DB

## [0.8.2] - 2023-04-26

### Fixed

- Get index name during Elasticsearch connection
- Attach new engine to metadata
- Scope schema inclusion in metadata and engine to Postgres alone

## [0.8.1] - 2022-01-13

### Added

- Custom separator support in Elasticsearch namespaces

## [0.8.0] - 2021-10-07

### Added

- `List` fields can contain `Dict` objects
- Stateful views for persistence and retrieval
- Auto-generated `message_id` on Events
- Pickling support for Protean exceptions

### Changed

- `fields` module moved under main package

### Fixed

- Fetch projection objects instead of IDs in `cache.get_all()`
- Generate embedded ValueObject data properly in `to_dict()`
- Derive SQLAlchemy field types correctly for embedded value object fields
- Elasticsearch adapter bugfixes and model enhancements

[Unreleased]: https://github.com/proteanhq/protean/compare/v0.15.0rc1...HEAD
[0.15.0rc1]: https://github.com/proteanhq/protean/compare/v0.14.2...v0.15.0rc1
[0.14.2]: https://github.com/proteanhq/protean/compare/v0.14.1...v0.14.2
[0.14.1]: https://github.com/proteanhq/protean/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/proteanhq/protean/compare/v0.13.1...v0.14.0
[0.13.1]: https://github.com/proteanhq/protean/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/proteanhq/protean/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/proteanhq/protean/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/proteanhq/protean/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/proteanhq/protean/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/proteanhq/protean/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/proteanhq/protean/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/proteanhq/protean/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/proteanhq/protean/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/proteanhq/protean/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/proteanhq/protean/compare/v0.7.1...v0.8.0
