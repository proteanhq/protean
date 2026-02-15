# Patterns & Recipes

This section contains in-depth guides for recurring patterns in domain-driven
applications built with Protean. Each pattern goes beyond the basics covered
in the main guides, providing architectural context, trade-off analysis, and
concrete implementation strategies.

These patterns **span multiple domain elements** and represent good practices
that Protean supports but does not enforce. They are the architectural wisdom
that separates a well-designed DDD system from one that merely uses DDD
terminology.

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

## Architecture & Quality

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

## Testing & Infrastructure

- **[Setting Up and Tearing Down Databases for Tests](setting-up-and-tearing-down-database-for-tests.md)**
  -- Manage database schema and test data lifecycles separately. Create schema
  once per session, reset data after every test, and clean up all infrastructure
  (providers, brokers, event stores) for fast, isolated integration tests.
