# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- Graceful resource cleanup on Engine shutdown: `Domain.close()` shuts down all infrastructure adapters (event store, brokers, caches, providers) in reverse initialization order. `Engine.shutdown()` now waits for in-flight message handlers to complete (10s bounded timeout) before closing infrastructure. New `close()` methods on `BaseBroker`, `BaseCache`, `EventStore`, and `Providers` port/registry classes with Redis adapter implementations.
- Observatory `/domain` page with sidebar navigation, `GET /api/domain/ir` endpoint that transforms the domain IR into a D3-ready graph structure (nodes, cross-aggregate links, clusters, flows, projections, stats), three view tabs (Topology, Event Flows, Process Managers), and aggregate detail panel. Foundation for the Domain Visualizer epic (#874).
- Observatory D3 force-directed aggregate topology graph on the `/domain` Topology tab. Interactive visualization with aggregate nodes showing name, stream category, ES/CQRS badge, and element counts; directed edges for cross-aggregate event handlers and process managers; zoom/pan, drag-to-reposition, hover highlighting of connected nodes, click-to-detail panel, mini-map overview, and legend.
- Observatory D3-based interactive causation graph for visualizing complex correlation chains. Adds a "Graph View" toggle alongside the existing CSS tree in the correlation view, with horizontal tree layout, zoom/pan, collapse/expand subtrees (Shift+click), hover path highlighting, cross-aggregate dashed links with latency labels, and click-to-detail. Auto-selects graph view for chains with depth > 2 or event count > 5.
- Observatory causation graph swimlane layout and fan-out polish: swimlane backgrounds grouped by stream category with colored headers and node accent bars, fan-out indicators showing branching multiplicity, timeline axis with elapsed time from root, color-coded legend (commands vs events, same vs cross-aggregate links, duration badges), progressive disclosure auto-collapsing deep branches for 50+ node chains, and a mini-map overview for navigating large graphs.
- Observatory live causation graph updates via SSE: when viewing a correlation chain, new messages with matching `correlation_id` animate into the D3 graph in real time. New nodes fade in with a highlight pulse, links animate smoothly, and all overlays (swimlanes, timeline axis, mini-map) refresh automatically. A "Live" badge appears when the chain has recent activity (< 30s). SSE events are debounced to 300ms to coalesce bursts.
- Observatory correlation view enhanced with handler attribution badges, processing duration badges, inter-step latency labels, and cross-aggregate boundary markers in the causation tree. New "End-to-End Duration" and "Streams Touched" summary stat cards added to the correlation view. Reuses `Observatory.fmt.duration()` for consistent formatting.
- Observatory "Traces" tab on the Timeline page with search inputs (aggregate ID, event type, command type, stream category), a recent traces list table, and deep-link support (`?view=traces&aggregate_id=...`). Each trace row navigates to the correlation chain view.
- Observatory trace search and recent traces API endpoints: `GET /timeline/traces/recent` returns the most recent correlation chains with summary statistics (correlation_id, root_type, event_count, started_at, streams), and `GET /timeline/traces/search` allows querying chains by aggregate_id, event_type, command_type, or stream_category. Both return `{traces: [...], count: int}`.
- Enrich `CausationNode` with `handler`, `duration_ms`, and `delta_ms` fields for waterfall/swimlane rendering in the Observatory. The correlation chain response now includes `total_duration_ms`. Handler and timing data are populated from Redis trace stream entries when available; all new fields gracefully fall back to `None` when trace data is unavailable. The CLI `protean events trace` command now displays handler names, processing durations, and inter-message latencies.
- `value_object_from_entity()` utility function that auto-generates a `BaseValueObject` subclass mirroring an entity's fields, eliminating manual field duplication for command/event payloads. Supports custom naming, field exclusion, and recursive conversion of `HasOne`/`HasMany` associations. Exported from `protean` top-level package.
- `ValueObjectFromEntity` field descriptor in `protean.fields` for inline use in commands and events, e.g. `List(content_type=ValueObjectFromEntity(OrderItem))`.
- `BaseEntity.from_value_object()` classmethod for converting value object payloads back into entity instances, completing the round-trip.

### Fixed

- Fix Observatory graph rendering with black overlays caused by DaisyUI 4→5 CSS variable mismatch. Update all `oklch(var(--b1))` references to DaisyUI 5 equivalents (`var(--color-base-100)`, `color-mix()`).
- Fix causation graph swimlane grouping treating command and event streams for the same aggregate as separate categories. Strip `:command` suffix in stream category extraction so both share one swimlane.
- Fix subscriber `causation_id` set to Redis Stream delivery ID instead of source event's `message_id`. Commands dispatched from subscribers now carry the correct causation link for cross-domain causation trees in the Observatory.
- Fix Observatory assigning the first domain's name to all events when multiple domains share a single MessageDB. Domain attribution is now derived from the stream name prefix (`<domain>::<aggregate>-<id>`).
- Fix persistence ordering in `BaseRepository`: aggregate root is now saved before child entities, and children before grandchildren (top-down). Previously the bottom-up ordering violated foreign-key constraints on databases that enforce them immediately (MSSQL, MySQL/InnoDB, SQLite with `PRAGMA foreign_keys`).
- Pre-commit hook documentation now recommends `repo: local` with `language: system` instead of `repo: https://github.com/proteanhq/protean`, since hooks call `derive_domain()` which imports user code that is unavailable in pre-commit's isolated virtualenv

### Added

- Generic `replace(**kwargs)` method on `BaseValueObject` for creating copies with selected fields changed, similar to `dataclasses.replace()`. Rejects unknown field names and re-validates invariants on the new instance.
- `domain.correlation_trace(correlation_id)` method that returns a flat, causally-ordered list of `CausationNode` objects for a correlation chain. Thin wrapper over `build_causation_tree()` surfaced at the domain level for downstream test assertions.
- `assert_chain()` test helper in `protean.testing` for validating message type sequences in correlation chains. Accepts both string type names and domain element classes.
- Auto-fix mode (`--fix`) for `protean-check-staleness` pre-commit hook: automatically regenerates stale IR and stages the updated file with `git add`, allowing the commit to proceed without manual intervention
- Multi-domain support for both pre-commit hooks (`protean-check-staleness`, `protean-check-compat`): new `[domains]` section in `.protean/config.toml` maps logical domain names to module paths, enabling a single hook entry to check all bounded contexts in a project. Each domain's IR is stored under `.protean/<name>/ir.json`. The `--domain` argument is now optional when `[domains]` is configured
- Structured logging integration for automatic correlation context injection: new `protean.integrations.logging` module with `ProteanCorrelationFilter` (stdlib `logging.Filter`) and `protean_correlation_processor` (structlog processor) that read `g.message_in_context` and inject `correlation_id` and `causation_id` into every log record. New `domain.configure_logging()` convenience method wires up both the filter and processor in one call. Safe no-op when no domain context is active.
- Add `correlation_id` and `causation_id` fields to `MessageTrace` dataclass and `TraceEmitter.emit()` in the Observatory tracing subsystem. All `handler.started`, `handler.completed`, `handler.failed`, `pm.transition`, `outbox.published`, `outbox.failed`, `message.acked`, `message.dlq` trace events now carry correlation and causation IDs from the processed message metadata. This enables the Observatory dashboard to group, filter, and link trace events by correlation chain. Backward compatible — callers that omit the new params get `None`.
- Add `protean.correlation_id` and `protean.causation_id` span attributes to `protean.handler.execute`, `protean.uow.commit`, `protean.outbox.process`, and `protean.outbox.publish` OTEL spans. Batch-level outbox spans only set these attributes when all messages in the batch share the same ID. This enables filtering all spans in a request chain by correlation ID in Jaeger, Datadog, or Tempo.
- X-Correlation-ID header support in `DomainContextMiddleware`: automatically extracts `X-Correlation-ID` (falling back to `X-Request-ID`) from incoming HTTP request headers and propagates the value as the default correlation ID during command processing. The response always includes an `X-Correlation-ID` header reflecting the ID that was used (from header, explicit `domain.process()` param, or auto-generated).
- End-to-end integration tests for correlation and causation ID propagation across command → event → handler → command → event → projection chains, external correlation ID flow, broker context propagation, event handler causation chain correctness, and OTEL span attribute verification (`tests/tracing/test_e2e_correlation_chain.py`).
- Deprecation support for domain elements and fields: new `deprecated` decorator option for all domain element types (`@domain.aggregate(deprecated={"since": "0.15", "removal": "0.18"})`) and `deprecated` parameter for fields (`String(deprecated="0.15")`), with normalized two-field metadata (`since` required, `removal` optional), sparse IR representation, `DEPRECATED_ELEMENT` and `DEPRECATED_FIELD` info-level diagnostics in `protean check`, and deprecation-aware contract diffing that classifies removals as "expected" (safe), "premature" (breaking), or "unexpected" (breaking) based on version comparison
- `.protean/config.toml` configuration support for IR compatibility checking: `CompatConfig` dataclass and `load_config()` loader in `protean.ir.config`. Supports `compatibility.strictness` (`strict`/`warn`/`off`), `compatibility.exclude` (FQN patterns), `compatibility.deprecation.min_versions_before_removal`, and `staleness.enabled`. Integrated with `protean ir diff`, `protean ir check`, and both pre-commit hooks (`protean-check-staleness`, `protean-check-compat`). `CompatConfig` and `load_config` are exported from `protean.ir`.
- Compatibility checking documentation guide covering `.protean/` directory structure, `config.toml` reference, breaking change rules, CLI commands, pre-commit hook setup, CI integration patterns, and deprecation lifecycle.
- Comprehensive documentation guide for correlation and causation IDs (`docs/guides/observability/correlation-and-causation.md`) covering the OOTB guarantee, external caller integration, full propagation flow with sequence diagram, causation chain semantics, cross-service boundary handling, OTEL relationship and span attribute reference, Observatory viewing, and structured logging setup. Cross-references added to FastAPI integration, subscribers, logging, OpenTelemetry, Observatory, message enrichment, and message tracing guides.
- Structured error payload enrichment with `correlation_id` in JSON body for all Protean exception handlers (`ValidationError`, `InvalidDataError`, `ValueError`, `ObjectNotFoundError`, `InvalidStateError`, `InvalidOperationError`). When a domain context is active via `DomainContextMiddleware`, error responses automatically include `correlation_id` matching the `X-Correlation-ID` response header. Routes outside domain context are unaffected.

### Changed

- Documentation now positions `to_dict()` as the only recommended serialization method for domain elements and warns against using Pydantic's `model_dump()` directly, which does not handle Reference fields, shadow fields, or datetime conversion correctly. Pydantic methods are hidden from generated API docs.

- Status field self-transitions are now validated against the transition map instead of being silently allowed. Assigning a status to its current value is rejected unless the state lists itself as a target (e.g., `CANCELLED: [CANCELLED]`). This catches re-entry bugs at the framework level and makes idempotent operations explicit in the transition declaration. Terminal states also reject self-assignment.

### Fixed

- Fix unreadable handler wiring and event flow diagrams by splitting into per-concern diagrams in Markdown output (#821)
- Fix Mermaid parse errors in cluster diagrams when invariant names contain commas or are unquoted
- Fix `TypeError: can't compare offset-naive and offset-aware datetimes` in outbox retry logic. Database adapters may return timezone-naive datetimes for `next_retry_at` and `locked_until`, causing comparisons with `datetime.now(timezone.utc)` to crash and block all outbox processing. Added shared `ensure_utc_aware()` utility to normalize naive datetimes before comparison.
- Fix flaky `test_mixed_error_scenarios` in `test_server_robustness.py`: increase Engine test_mode processing cycles from 3 to 10 so all subscription types (events, commands, broker messages) have enough time to be scheduled and process their messages under CI load
- Bridge `correlation_id` from external broker messages to subscriber-triggered commands: `Engine.handle_broker_message()` now extracts `correlation_id` from the incoming message's `metadata.domain.correlation_id` (Protean external format) and sets it on the stub message context. When no correlation ID is present, a fresh UUID is auto-generated. This ensures the cross-service correlation chain is preserved through subscriber processing.
- Preserve outer message context across nested `domain.process()` calls: `CommandProcessor.process()` now saves and restores the previous `g.message_in_context` instead of unconditionally clearing it. This fixes correlation ID loss when a subscriber dispatches multiple commands within a single handler invocation.

### Added

- Pre-commit framework hooks: ship `.pre-commit-hooks.yaml` so downstream projects can add `protean-check-staleness` (blocks commit if `.protean/ir.json` is stale) and `protean-check-compat` (blocks commit if breaking IR changes detected against a git baseline) as pre-commit hooks. Console script entry points `protean-check-staleness` and `protean-check-compat` registered in `pyproject.toml`.
- Enhanced `protean ir diff` with auto-baseline and git support: when `--domain` is provided without `--left`/`--right`, automatically loads `.protean/ir.json` as the baseline and diffs against the live domain. New `--base <commit>` flag loads `.protean/ir.json` from any git commit via `git show`, enabling comparisons against `HEAD`, `main`, or any tag. CI-friendly exit codes: 0 (no changes), 1 (breaking changes), 2 (non-breaking changes only). New `load_ir_from_commit()` and `GitError` in `protean.ir.git` provide the git integration layer, exported from `protean.ir`.
- IR staleness detection: `check_staleness(domain_module, protean_dir) -> StalenessResult` in `protean.ir.staleness` compares the live domain's IR checksum against the materialized `.protean/ir.json`. Returns a `StalenessResult` with `status` (`fresh`, `stale`, or `no_ir`) and both checksums. The `protean ir check` CLI command exposes this with `--domain`, `--dir`, `--format json|text`, and exit codes 0 (fresh), 1 (stale), 2 (no IR found). `StalenessResult`, `StalenessStatus`, and `check_staleness` are exported from `protean.ir`.
- `classify_changes(diff_result, left_ir, right_ir) -> CompatibilityReport` in `protean.ir.diff` — walks all persisted/serialized IR sections (aggregates, entities, value objects, commands, events, database models, projections) and applies a comprehensive breaking-change ruleset: required field added without default → breaking, optional/defaulted field added → safe, field removed → breaking, field type changed → breaking, element removed → breaking, element added → safe, visibility public→internal → breaking, visibility internal→public → safe, `__type__` string changed → breaking. `CompatibilityChange` and `CompatibilityReport` dataclasses are exported from `protean.ir`.
- Real-time SSE updates for Observatory Timeline: live event prepending via `handler.completed`/`outbox.published` trace events with position-based deduplication, new-event row highlight animation, "N new events — click to scroll to top" toast notification when scrolled down, and immediate stat card refresh on each trace event
- Correlation chain and aggregate history sub-views for the Observatory Timeline page: vertical causation tree visualization for correlation chains, chronological aggregate event history with version labels, clickable correlation ID and stream name links in event detail panel, URL deep-linking (`/timeline?correlation={id}`, `/timeline?stream={category}&aggregate={id}`), and back-to-list navigation with browser history support
- Observatory Timeline page: chronological event browser with filter bar (stream category, event type, aggregate ID, kind), cursor-based pagination with infinite scroll, event detail panel with full payload/metadata and correlation chain links, summary stat cards, deep-linking support, and `g→t` keyboard shortcut
- OpenTelemetry integration documentation: comprehensive guide covering configuration, span catalog, metrics catalog, TraceParent propagation, FastAPI auto-instrumentation, APM setup guides (Jaeger, Grafana Tempo, Datadog), Observatory vs OTel positioning, and `/metrics` convergence
- End-to-end integration tests for unified OTel span hierarchy and Observatory trace emission: validates complete span tree from command → handler → UoW → repository → event store, verifies parent-child relationships across all layers, confirms complementary (non-redundant) attributes at each span level, and ensures Observatory traces fire correctly alongside OTel spans both with telemetry enabled and disabled
- OpenTelemetry SDK foundation with optional `telemetry` extra (`pip install protean[telemetry]`), `[telemetry]` configuration section, `telemetry.py` module for provider initialization, and `Domain.tracer`/`Domain.meter` lazy properties — graceful no-op when packages are not installed or telemetry is disabled
- OpenTelemetry spans for command processing and handler dispatch: `protean.command.process` (with command type, id, stream, correlation_id attributes), `protean.command.enrich` (child span), `protean.handler.execute` (with handler name and type, covers command handlers, event handlers, projectors, and process managers), and `protean.query.dispatch` — with exception recording and ERROR status on handler failures
- OpenTelemetry spans for infrastructure operations: `protean.uow.commit` (with event_count and session_count attributes), `protean.repository.add` and `protean.repository.get` (with aggregate type and provider attributes, covers both standard and event-sourced repositories), and `protean.event_store.append` (with stream, message_type, and position attributes) — all spans participate in the same trace as the originating command/query
- OpenTelemetry spans for server subscriptions and outbox processor: `protean.engine.handle_message` (with handler name, message type/id, stream category, worker_id, and subscription_type attributes), `protean.outbox.process` (per batch with batch_size, processor_id, is_external, successful_count), and `protean.outbox.publish` (per message with message_id, stream_category, message_type) — with exception recording and ERROR status on failures, and parent-child span relationships between process and publish spans
- Bridge W3C TraceParent headers with OpenTelemetry context propagation: `extract_context_from_traceparent()` and `inject_traceparent_from_context()` helpers in `telemetry.py`, context extraction in `Engine.handle_message()` and `CommandProcessor.process()` so processing spans parent under incoming traces, context injection in `CommandProcessor.enrich()` and `BaseAggregate.raise_()` so commands and events carry the active span's traceparent forward to downstream handlers
- Auto-instrument FastAPI endpoints with OpenTelemetry via `instrument_app(app, domain)` in `protean.integrations.fastapi` — wraps `opentelemetry-instrumentation-fastapi` with domain-scoped tracer/meter providers so HTTP request spans automatically parent command processing spans through OTEL context propagation, with graceful no-op when telemetry is disabled or packages are not installed
- OpenTelemetry metrics for domain operations: counters (`protean.command.processed`, `protean.handler.invocations`, `protean.uow.commits`, `protean.outbox.published`, `protean.outbox.failed`) and histograms (`protean.command.duration`, `protean.handler.duration`, `protean.uow.events_per_commit`, `protean.outbox.latency`) — instruments are cached per domain via `DomainMetrics` and use no-op fallbacks when OTel is not installed
- Hybrid `/metrics` endpoint convergence: when `opentelemetry-exporter-prometheus` is installed and telemetry is enabled, the Observatory `/metrics` endpoint serves OTel-generated Prometheus text (via `PrometheusMetricReader`) with infrastructure metrics exposed as `ObservableGauge` callbacks; falls back to the original hand-rolled implementation when OTel is not available
- Correlation chain and aggregate history API endpoints for the Observatory: `GET /api/timeline/correlation/{correlation_id}` (all events in a correlation chain with causation tree) and `GET /api/timeline/aggregate/{stream_category}/{aggregate_id}` (full event history for one aggregate instance with version info)
- Event store timeline query API endpoints for the Observatory: `GET /api/timeline/events` (paginated, filterable event list from `$all` stream), `GET /api/timeline/events/{message_id}` (single event detail with full payload and metadata), and `GET /api/timeline/stats` (summary statistics including total events, active streams, and throughput)
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
