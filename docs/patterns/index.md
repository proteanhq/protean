# Patterns

Patterns are **prescriptive understanding** -- they explain *what to do* about
a recurring design problem and *why*, with explicit boundaries on when the
guidance applies and when it doesn't.

Unlike [guides](../guides/index.md), which walk you through specific tasks, and
[concepts](../concepts/index.md), which explain how things work, patterns address
recurring architectural decisions in domain-driven applications. Each pattern
diagnoses a problem, prescribes a principle, provides worked examples and
anti-patterns, and states when *not* to apply it.

These patterns **span multiple domain elements** and represent good practices
that Protean supports but does not enforce. They are the architectural wisdom
that separates a well-designed DDD system from one that merely uses DDD
terminology.

## Reading Paths

If you are new to these patterns, these sequences build on each other:

**Aggregate boundaries** -- why small, how they communicate, how events flow:
:   [Design Small Aggregates](design-small-aggregates.md) →
    [One Aggregate Per Transaction](one-aggregate-per-transaction.md) →
    [Design Events for Consumers](design-events-for-consumers.md)

**Behavior placement** -- where logic lives, how to keep handlers thin, how to test:
:   [Encapsulate State Changes](encapsulate-state-changes.md) →
    [Thin Handlers, Rich Domain](thin-handlers-rich-domain.md) →
    [Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md)

**Idempotency** -- from identity generation through command and event deduplication:
:   [Creating Identities Early](creating-identities-early.md) →
    [Command Idempotency](command-idempotency.md) →
    [Idempotent Event Handlers](idempotent-event-handlers.md)

**Cross-domain communication** -- relating, consuming, and contracting across boundaries:
:   [Connecting Concepts Across Bounded Contexts](connect-concepts-across-domains.md) →
    [Consuming Events from Other Domains](consuming-events-from-other-domains.md) →
    [Sharing Event Classes Across Domains](sharing-event-classes-across-domains.md)

**Cross-system integration** -- publishing, consuming, and contracting across system boundaries:
:   [Fact Events as Integration Contracts](fact-events-as-integration-contracts.md) →
    [Publishing Events to External Brokers](publishing-events-to-external-brokers.md) →
    [Consuming Events from Other Domains](consuming-events-from-other-domains.md) →
    [CloudEvents as a Boundary Contract](cloudevents-interoperability.md)

**Read models** -- designing, deploying, and evolving projections:
:   [Design Projection Granularity](projection-granularity.md) →
    [Projection Rebuilds as Deployment](projection-rebuilds-as-deployment.md) →
    [Bridge Eventual Consistency](eventual-consistency-in-uis.md)

**Production resilience** -- errors, concurrency, and operational concerns:
:   [Classify Async Processing Errors](classify-async-processing-errors.md) →
    [Optimistic Concurrency as Design Tool](optimistic-concurrency-as-design-tool.md) →
    [Aggregate State Machines](aggregate-state-machines.md)

---

## Aggregate Design

- **[Design Small Aggregates](design-small-aggregates.md)** -- Draw aggregate
  boundaries around consistency requirements, not data relationships. Reference
  other aggregates by identity, not by embedding. Use domain events for
  cross-aggregate communication.

- **[One Aggregate Per Transaction](one-aggregate-per-transaction.md)** --
  Modify exactly one aggregate per command handler or application service method.
  Cross-aggregate side effects flow through domain events, each processed in
  its own transaction.

- **[Optimistic Concurrency as a Design Tool](optimistic-concurrency-as-design-tool.md)**
  -- Classify version conflicts by business meaning instead of treating them as
  generic errors. Last-writer-wins for harmless races, domain-specific
  exceptions for real contention, and conditional retries for mergeable
  operations.

- **[Encapsulate State Changes in Named Methods](encapsulate-state-changes.md)**
  -- Express every state change as a named method on the aggregate that captures
  business intent. Methods validate preconditions, mutate state, and raise
  events. Handlers become thin orchestrators.

- **[Replace Primitives with Value Objects](replace-primitives-with-value-objects.md)**
  -- Extract strings, integers, and floats into value objects when they have
  format rules, composition, or operations. Make invalid states
  unrepresentable at the type level.

- **[Factory Methods for Aggregate Creation](factory-methods-for-aggregate-creation.md)**
  -- Encapsulate complex or repeated aggregate construction in factory
  classmethods on the aggregate itself. When construction needs repository
  access or external data translation, extract to a standalone factory class.
  Keeps handlers thin and construction knowledge centralized.

- **[Model Aggregate Lifecycle as a State Machine](aggregate-state-machines.md)**
  -- Define an explicit enum of lifecycle states and use guarded transition
  methods to enforce valid state changes. Makes invalid transitions
  impossible and the aggregate's lifecycle visible in one place.

## Event-Driven Patterns

- **[Design Events for Consumers](design-events-for-consumers.md)** -- Events
  should carry enough context for consumers to act independently, without
  querying back to the source aggregate. Covers delta vs fact events,
  projection-driven event design, and cross-domain events.

- **[Idempotent Event Handlers](idempotent-event-handlers.md)** -- Every event
  handler must produce the same result whether it processes an event once or
  multiple times. Covers naturally idempotent operations, deduplication
  strategies, and upsert patterns.

- **[Event Versioning and Evolution](event-versioning-and-evolution.md)** --
  Events are immutable facts stored forever, but domain models evolve. Covers
  backward-compatible changes, new event types, upcasting, tolerant readers,
  and migration strategies.

- **[Command Idempotency](command-idempotency.md)** -- Ensuring that processing
  the same command multiple times produces the same effect as processing it
  once. Covers Protean's three-layer idempotency model, idempotency keys,
  and handler-level strategies for different operation types.

- **[Coordinating Long-Running Processes](coordinating-long-running-processes.md)**
  -- Use a process manager to coordinate multi-step workflows that span
  multiple aggregates. Covers declarative correlation, lifecycle management,
  idempotent handlers via status guards, explicit compensation for every
  forward step, out-of-order event handling, external timeout strategies,
  and minimal state fields.

- **[Message Tracing in Event-Driven Systems](message-tracing.md)** -- Thread
  `correlation_id` and `causation_id` through every command and event in a
  causal chain. Enables end-to-end debugging, auditing, and cross-service
  traceability.

- **[Enrich Messages with Cross-Cutting Metadata](message-enrichment.md)** --
  Inject tenant IDs, user context, request trace IDs, and feature flags into
  every event and command via enrichment hooks. Keeps the domain model clean
  while ensuring all messages carry operational context in
  `metadata.extensions`.

- **[Multi-Tenancy in Event-Driven Systems](multi-tenancy.md)** --
  Row-level tenant isolation using `g.tenant_id`, enrichers,
  `metadata.extensions`, and automatic context propagation through async
  processing. Covers the end-to-end flow from middleware through event store
  to async handlers, with future directions for schema-per-tenant and
  database-per-tenant strategies.

- **[CloudEvents as a Boundary Contract](cloudevents-interoperability.md)** --
  Serialize Protean events to the CloudEvents v1.0 standard at system
  boundaries. Keep internal metadata DDD-native; use `to_cloudevent()` and
  `from_cloudevent()` as an anti-corruption layer for interoperability with
  external systems, Kafka topics, and webhooks.

## Architecture & Quality

- **[Organize by Domain Concept](organize-by-domain-concept.md)** -- The
  folder tree owns the "what" (domain concepts); the framework owns the
  "which kind" (layer, side, boundary). Organize by aggregate, colocate
  capabilities, separate projections, and let Protean's decorators carry
  architectural metadata.

- **[Validation Layering](validation-layering.md)** -- Different kinds of
  validation belong at different layers: field constraints for types, value
  object invariants for concept rules, aggregate invariants for business rules,
  and handler guards for contextual checks.

- **[Thin Handlers, Rich Domain](thin-handlers-rich-domain.md)** -- Handlers
  orchestrate (load, call, save). Aggregates and domain services contain all
  business logic. Prevents the anemic domain model anti-pattern and makes
  domain logic directly testable.

- **[Choose Between Application Services and Command Handlers](application-service-vs-command-handler.md)**
  -- Application services for synchronous, API-facing operations that return
  results. Command handlers for async, event-driven processing via
  `domain.process()`. Never both for the same aggregate operation.

- **[Design Projection Granularity Around Consumer Needs](projection-granularity.md)**
  -- Shape each projection around a UI view or API resource, not around domain
  entities or API endpoints. Use cross-aggregate projectors, cache-backed
  projections for volatile data, and shared projections with optional fields
  to avoid both the mirror-the-aggregate and per-endpoint anti-patterns.

- **[Treat Projection Rebuilds as a Deployment Strategy](projection-rebuilds-as-deployment.md)**
  -- Rebuild projections from the event store instead of migrating database
  schemas. Covers simple rebuilds, blue-green deployment with `schema_name`,
  monitoring progress with `RebuildResult`, and using priority lanes for
  background rebuilds.

- **[Bridge the Eventual Consistency Gap in User Interfaces](eventual-consistency-in-uis.md)**
  -- Three strategies for handling the delay between CQRS writes and reads:
  optimistic UI for immediate local display, returning write-side results for
  post-write detail pages, and version polling for critical confirmations.

- **[Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md)**
  -- Test aggregates, value objects, and domain services directly, without
  handlers, repositories, or infrastructure. Domain unit tests should be the
  majority of your test suite.

- **[Dual-Mode Testing](dual-mode-testing.md)** -- Run the same test suite
  against in-memory adapters for fast feedback and real infrastructure for
  final validation. Switch modes with a single configuration flag, zero code
  changes.

- **[Test Event-Driven Flows End-to-End](testing-event-driven-flows.md)** --
  Three testing levels for event chains: domain unit tests for business logic,
  sync flow tests for wiring verification, and async E2E tests with the Engine
  in test mode for subscription and priority lane validation.

- **[Setting Up and Tearing Down Databases](setting-up-and-tearing-down-database-for-tests.md)**
  -- Separate the schema lifecycle (create once, drop once) from the data
  lifecycle (reset after every test). Applies to all infrastructure, not just
  databases.

## Identity & Communication

- **[Creating Identities Early](creating-identities-early.md)** -- Generating
  aggregate identities at the point of creation (or earlier, at the client or
  API boundary) rather than deferring to the database. Covers why early identity
  generation matters for commands, events, idempotency, and distributed systems,
  and how Protean's `Auto` field makes it the default.

- **[Connecting Concepts Across Bounded Contexts](connect-concepts-across-domains.md)**
  -- Keeping the same real-world concept synchronized across multiple bounded
  contexts without coupling them. Covers identity correlation, event propagation,
  fact events, anti-corruption layers via subscribers, and cross-context
  projections.

- **[Consuming Events from Other Domains](consuming-events-from-other-domains.md)**
  -- Using subscribers as anti-corruption layers to receive external events,
  translate them into your domain's language, and dispatch internal commands
  or events. Nothing downstream knows the stimulus came from outside.

- **[Sharing Event Classes Across Domains](sharing-event-classes-across-domains.md)**
  -- Share schemas (message contracts), not code (class definitions). Each domain
  defines its own event classes that conform to the agreed-upon schema. Use
  contract tests to verify compatibility without code dependencies.

- **[Use Fact Events as Cross-Context Integration Contracts](fact-events-as-integration-contracts.md)**
  -- Enable `fact_events=True` on aggregates consumed by other bounded contexts.
  External consumers receive complete state snapshots instead of reconstructing
  state from granular deltas. Reserve delta events for internal reactions where
  semantic meaning is essential.

- **[Publishing Events to External Brokers](publishing-events-to-external-brokers.md)**
  -- Deliver `published=True` events to external brokers via the outbox pattern.
  Each external broker gets its own outbox row with independent retry and a
  stripped metadata envelope. Internal processing is never blocked by external
  broker failures.

## Operations

- **[Running Data Migrations with Priority Lanes](running-data-migrations-with-priority-lanes.md)**
  -- Route migration events to a separate backfill lane so they do not block
  production event processing. Covers the migration script pattern, monitoring,
  and anti-patterns for data backfills.

- **[Classify and Handle Async Processing Errors](classify-async-processing-errors.md)**
  -- Override `handle_error()` in every production handler. Classify failures as
  transient (let outbox retry), data errors (route to DLQ), or logic errors
  (alert immediately). Prevent silent read-model drift.

- **[Temporal Queries for Audit, Debugging, and Compliance](temporal-queries.md)**
  -- Use `at_version` and `as_of` on event-sourced repositories as first-class
  operations for compliance audits, incident investigation, and customer support.
  Returned aggregates are read-only, safe to expose through API endpoints.

---

!!! note "Related how-to guides"
    Procedural guides for testing and infrastructure live in the
    **Guides** section:

    - [Testing Guide](../guides/testing/index.md) -- Overview of Protean's testing strategy and tools.
    - [Using Priority Lanes](../guides/server/using-priority-lanes.md) -- Enable and configure priority lanes for background workloads.
