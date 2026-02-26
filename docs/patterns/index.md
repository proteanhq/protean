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
  multiple aggregates. Declarative correlation, lifecycle management, and
  compensation handling replace ad-hoc event handler chains.

- **[Message Tracing in Event-Driven Systems](message-tracing.md)** -- Thread
  `correlation_id` and `causation_id` through every command and event in a
  causal chain. Enables end-to-end debugging, auditing, and cross-service
  traceability.

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

- **[Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md)**
  -- Test aggregates, value objects, and domain services directly, without
  handlers, repositories, or infrastructure. Domain unit tests should be the
  majority of your test suite.

- **[Dual-Mode Testing](dual-mode-testing.md)** -- Run the same test suite
  against in-memory adapters for fast feedback and real infrastructure for
  final validation. Switch modes with a single configuration flag, zero code
  changes.

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

## Operations

- **[Running Data Migrations with Priority Lanes](running-data-migrations-with-priority-lanes.md)**
  -- Route migration events to a separate backfill lane so they do not block
  production event processing. Covers the migration script pattern, monitoring,
  and anti-patterns for data backfills.

---

!!! note "Related how-to guides"
    Procedural guides for testing and infrastructure live in the
    **Guides** section:

    - [Testing Guide](../guides/testing/index.md) -- Overview of Protean's testing strategy and tools.
    - [Using Priority Lanes](../guides/server/using-priority-lanes.md) -- Enable and configure priority lanes for background workloads.
