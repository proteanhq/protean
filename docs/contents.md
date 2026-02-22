# Contents

A complete listing of every page in the Protean documentation. Use your
browser's search (`Ctrl+F` / `Cmd+F`) to find any topic.

---

## Getting Started

- [Installation](./guides/getting-started/installation.md) -- Set up Python and install Protean.
- [Quickstart](./guides/getting-started/quickstart.md) -- Build a domain in 5 minutes with in-memory adapters.

### Tutorial: Building Bookshelf

A guided, end-to-end walkthrough of building a complete online bookstore.

**Part I -- Getting Started**

- [1. Your First Aggregate](./guides/getting-started/tutorial/01-your-first-aggregate.md) -- Create the foundation with a working Book aggregate.
- [2. Fields and Identity](./guides/getting-started/tutorial/02-fields-and-identity.md) -- Explore field types, options, and how identity works.

**Part II -- The Domain Model**

- [3. Value Objects](./guides/getting-started/tutorial/03-value-objects.md) -- Model rich, descriptive concepts instead of primitives.
- [4. Entities and Associations](./guides/getting-started/tutorial/04-entities-and-associations.md) -- Build the Order aggregate with entities and relationships.
- [5. Business Rules](./guides/getting-started/tutorial/05-business-rules.md) -- Add invariants and encapsulate behavior in aggregate methods.

**Part III -- Commands and Events**

- [6. Commands](./guides/getting-started/tutorial/06-commands.md) -- Formalize state changes with commands and command handlers.
- [7. Domain Events](./guides/getting-started/tutorial/07-events.md) -- Define domain events and raise them from aggregates.
- [8. Event Handlers](./guides/getting-started/tutorial/08-event-handlers.md) -- Process events and trigger side effects.

**Part IV -- Services and Read Models**

- [9. Application Services](./guides/getting-started/tutorial/09-application-services.md) -- Create a synchronous coordination layer.
- [10. Domain Services](./guides/getting-started/tutorial/10-domain-services.md) -- Encapsulate business logic spanning multiple aggregates.
- [11. Projections](./guides/getting-started/tutorial/11-projections.md) -- Build read-optimized views from events.

**Part V -- Infrastructure**

- [12. Persistence](./guides/getting-started/tutorial/12-persistence.md) -- Connect to real databases using configuration.
- [13. Async Processing](./guides/getting-started/tutorial/13-async-processing.md) -- Switch to asynchronous processing for scalability.
- [14. Event Sourcing](./guides/getting-started/tutorial/14-event-sourcing.md) -- Store events instead of current state.

**Part VI -- Quality**

- [15. Testing](./guides/getting-started/tutorial/15-testing.md) -- Testing strategies for every layer of the application.

---

## Guides

Comprehensive reference organized by topic. Each guide goes deep on a
specific area.

- [Guide Overview](./guides/index.md) -- How the guides are organized and where to start.
- [How Do I...?](./how-do-i.md) -- Task-oriented index: find the right guide by what you're trying to do.

### Choose a Path

- [Architectural Pathways](./guides/pathways/index.md) -- Three approaches that build on each other.
- [DDD Pathway](./guides/pathways/ddd.md) -- Aggregates, application services, and repositories.
- [CQRS Pathway](./guides/pathways/cqrs.md) -- Separate reads from writes with commands and projections.
- [Event Sourcing Pathway](./guides/pathways/event-sourcing.md) -- Derive state from event replay.

### Set Up the Domain

- [The Domain Object](./guides/compose-a-domain/index.md) -- The composition root that manages elements, configuration, and adapters.
- [Register Elements](./guides/compose-a-domain/register-elements.md) -- How elements register themselves with the domain.
- [Initialize the Domain](./guides/compose-a-domain/initialize-domain.md) -- Call `init()` to wire everything together.
- [Activate the Domain](./guides/compose-a-domain/activate-domain.md) -- Bind the domain to a context for use.
- [When to Compose](./guides/compose-a-domain/when-to-compose.md) -- Lifecycle and timing of domain composition.
- [Element Decorators](./guides/compose-a-domain/element-decorators.md) -- Decorators that construct and register domain elements.
- [Object Model](./guides/essentials/object-model.md) -- Common structure and traits shared by all domain elements.

### Define Domain Elements

- [Defining Concepts](./guides/domain-definition/index.md) -- Foundational domain concepts using DDD tactical patterns.
- [Aggregates](./guides/domain-definition/aggregates.md) -- Model domain concepts with unique identity.
- [Entities](./guides/domain-definition/entities.md) -- Objects with identity that compose aggregates.
- [Value Objects](./guides/domain-definition/value-objects.md) -- Immutable descriptive objects identified by their attributes.
- [Expressing Relationships](./guides/domain-definition/relationships.md) -- Model associations between domain elements.
- [Events](./guides/domain-definition/events.md) -- Model past changes as discrete, meaningful facts.
- [Deciding Between Elements](./guides/domain-definition/deciding-between-elements.md) -- Checklists and decision flows for choosing element types.

**Fields**

- [Fields Overview](./guides/domain-definition/fields/index.md) -- Field types, attributes, options, and functionalities.
- [Defining Fields](./guides/domain-definition/fields/defining-fields.md) -- Three styles for declaring fields: annotation, assignment, and raw Pydantic.
- [Simple Fields](./guides/domain-definition/fields/simple-fields.md) -- String, Text, Integer, Float, Boolean, and other primitives.
- [Container Fields](./guides/domain-definition/fields/container-fields.md) -- Fields that hold and embed value objects.
- [Association Fields](./guides/domain-definition/fields/association-fields.md) -- HasOne, HasMany, and Reference fields for relationships.
- [Common Arguments](./guides/domain-definition/fields/arguments.md) -- Shared field arguments like `required`, `default`, and `description`.
- [Identity](./guides/essentials/identity.md) -- Identity generation strategies, types, and configuration.

### Add Rules and Behavior

- [Domain Behavior](./guides/domain-behavior/index.md) -- Enforcing business rules through validations, invariants, and methods.
- [Validations](./guides/domain-behavior/validations.md) -- Field-level validation using types, options, and custom validators.
- [Invariants](./guides/domain-behavior/invariants.md) -- Business rules that must always hold true within an aggregate.
- [Mutating Aggregates](./guides/domain-behavior/aggregate-mutation.md) -- Modify state through named methods reflecting actions and events.
- [Raising Events](./guides/domain-behavior/raising-events.md) -- Notify other parts of the system through domain events.
- [Domain Services](./guides/domain-behavior/domain-services.md) -- Complex domain logic that spans multiple aggregates.

### Change State

- [Changing State](./guides/change-state/index.md) -- Mechanisms for state changes: services, commands, and handlers.
- [Application Services](./guides/change-state/application-services.md) -- Bridge between the API layer and the domain model.
- [Commands](./guides/change-state/commands.md) -- Data transfer objects expressing intention to change state.
- [Command Handlers](./guides/change-state/command-handlers.md) -- Process commands and execute domain logic.
- [Repositories](./guides/change-state/repositories.md) -- Define custom repositories, the DAO layer, and database-specific persistence.
- [Persist Aggregates](./guides/change-state/persist-aggregates.md) -- Save aggregates using a repository's `add` method.
- [Retrieve Aggregates](./guides/change-state/retrieve-aggregates.md) -- QuerySets, filtering, Q objects, bulk operations, and result navigation.
- [Temporal Queries](./guides/change-state/temporal-queries.md) -- Reconstitute event-sourced aggregates at a specific version or point in time.
- [Unit of Work](./guides/change-state/unit-of-work.md) -- Automatic transaction management for aggregate changes.

### React to Changes

- [Consuming State Changes](./guides/consume-state/index.md) -- React to state changes through handlers, projections, and subscribers.
- [Event Handlers](./guides/consume-state/event-handlers.md) -- Consume events to sync state or trigger side effects.
- [Process Managers](./guides/consume-state/process-managers.md) -- Coordinate multi-step processes across aggregates with stateful, event-sourced coordination.
- [Projections](./guides/consume-state/projections.md) -- Create read-optimized views built from events.
- [Subscribers](./guides/consume-state/subscribers.md) -- Consume messages from external brokers.
- [Stream Categories](./guides/essentials/stream-categories.md) -- How messages are organized and routed.
- [Event Upcasting](./guides/event-upcasting.md) -- Transforming old event schemas to match the current version during replay.

### Run in Production

- [Configuration](./guides/essentials/configuration.md) -- Configure Protean through domain.toml and environment variables.
- [FastAPI Integration](./guides/fastapi/index.md) -- Domain context middleware, exception handlers, and best practices for using Protean with FastAPI.

**Server**

- [Server Overview](./guides/server/index.md) -- Asynchronous message processing engine for events, commands, and external messages.
- [Engine Architecture](./guides/server/engine.md) -- Core async processing, managing subscriptions and lifecycle.
- [Subscriptions](./guides/server/subscriptions.md) -- Connect handlers to message sources.
- [Subscription Types](./guides/server/subscription-types.md) -- Stream and EventStore subscriptions for different use cases.
- [Subscription Configuration](./guides/server/configuration.md) -- Flexible configuration with priority hierarchy.
- [Outbox Pattern](./guides/server/outbox.md) -- Reliable message delivery via same-transaction storage.
- [Observability](./guides/server/observability.md) -- Real-time tracing, the Observatory monitoring server, SSE streaming, and Prometheus metrics.
- [Running the Server](./guides/server/running.md) -- Start, configure, and operate the Protean server.

**CLI**

- [CLI Overview](./guides/cli/index.md) -- The `protean` command-line interface for scaffolding and management.
- [Domain Discovery](./guides/cli/discovery.md) -- Use `--domain` to load and initialize domains.
- [`protean new`](./guides/cli/new.md) -- Initialize new projects.
- [`protean shell`](./guides/cli/shell.md) -- Interactive shell with the domain pre-loaded.
- [`protean server`](./guides/cli/server.md) -- Run the async background message processing server.
- [`protean docs`](./guides/cli/docs.md) -- Live preview server for documentation.
- [`protean test`](./guides/cli/test.md) -- Run tests with category and technology options.
- [`protean snapshot`](./guides/cli/snapshot.md) -- Create snapshots for event-sourced aggregates.
- [`protean projection`](./guides/cli/projection.md) -- Rebuild projections by replaying events from the event store.
- [`protean events`](./guides/cli/events.md) -- Inspect the event store: read streams, view stats, search events, and trace aggregate history.
- [Type Checking](./guides/type-checking.md) -- Static type checking with the Protean mypy plugin.

### Test Your Application

- [Testing Strategy](./guides/testing/index.md) -- Layered testing approach with fast in-memory adapters.
- [Domain Model Tests](./guides/testing/domain-model-tests.md) -- Unit tests for aggregates, entities, value objects, and invariants.
- [Application Tests](./guides/testing/application-tests.md) -- Validate commands, handlers, and services.
- [Event Sourcing Tests](./guides/testing/event-sourcing-tests.md) -- Fluent test DSL for event-sourced aggregates using `protean.testing.given`.
- [Integration Tests](./guides/testing/integration-tests.md) -- Verify behavior with real infrastructure.
- [Fixtures and Patterns](./guides/testing/fixtures-and-patterns.md) -- Reusable pytest fixtures and conftest recipes.

---

## Core Concepts

Architectural theory and the building blocks of domain-driven systems.

### Foundations

- [Ubiquitous Language](./core-concepts/ubiquitous-language.md) -- The shared vocabulary between domain experts and developers.
- [Bounded Contexts](./core-concepts/bounded-contexts.md) -- Boundaries within which a domain model is defined and applicable.
- [Analysis Model](./core-concepts/analysis-model.md) -- Bridging the gap between domain understanding and software implementation.
- [Identity](./core-concepts/identity.md) -- The property that distinguishes one domain object from all others.
- [Invariants](./core-concepts/invariants.md) -- Business rules that must always hold true within a domain concept.
- [Changing State](./core-concepts/changing-state.md) -- Principles governing how state transitions occur in DDD.
- [Streams](./core-concepts/streams.md) -- The primary unit of organization in evented systems.

### Architecture Patterns

- [Domain-Driven Design](./core-concepts/ddd.md) -- Tactical elements and their roles in the DDD pattern.
- [CQRS](./core-concepts/cqrs.md) -- Separating read and write responsibilities.
- [Event Sourcing](./core-concepts/event-sourcing.md) -- Deriving state from replaying event sequences.
- [Choosing an Architecture](./core-concepts/architecture-decision.md) -- When to use CQRS vs Event Sourcing.

### Building Blocks

- [Domain Elements Overview](./core-concepts/domain-elements/index.md) -- Tactical patterns organized into four layers.
- [Aggregates](./core-concepts/domain-elements/aggregates.md) -- Clusters of objects treated as a single unit for data changes.
- [Entities](./core-concepts/domain-elements/entities.md) -- Mutable objects with distinct identity.
- [Value Objects](./core-concepts/domain-elements/value-objects.md) -- Immutable elements distinguished by properties.
- [Domain Services](./core-concepts/domain-elements/domain-services.md) -- Domain logic that doesn't fit within aggregates.
- [Events](./core-concepts/domain-elements/events.md) -- Immutable facts indicating state changes.
- [Commands](./core-concepts/domain-elements/commands.md) -- Intentions to change system state.
- [Command Handlers](./core-concepts/domain-elements/command-handlers.md) -- Process commands and execute domain logic.
- [Event Handlers](./core-concepts/domain-elements/event-handlers.md) -- React to events with side effects and state synchronization.
- [Application Services](./core-concepts/domain-elements/application-services.md) -- Coordinate use cases at the boundary between external world and domain.
- [Repositories](./core-concepts/domain-elements/repositories.md) -- Collection-oriented persistence abstraction for aggregates.
- [Subscribers](./core-concepts/domain-elements/subscribers.md) -- Consume messages from external brokers.
- [Projections](./core-concepts/domain-elements/projections.md) -- Read-optimized denormalized views.
- [Projectors](./core-concepts/domain-elements/projectors.md) -- Specialized event handlers that maintain projections.
- [Process Managers](./core-concepts/domain-elements/process-managers.md) -- Stateful coordinators for multi-step processes across aggregates.

---

## Adapters

Plug-in infrastructure that keeps your domain code free of technology
dependencies.

- [Adapters Overview](./adapters/index.md) -- Ports and Adapters (Hexagonal Architecture) in Protean.
- [Adapter Internals](./adapters/internals.md) -- How database adapter components work together.

### Database

- [Database Providers](./adapters/database/index.md) -- Overview of supported database adapters.
- [PostgreSQL](./adapters/database/postgresql.md) -- SQLAlchemy-based adapter for PostgreSQL.
- [Elasticsearch](./adapters/database/elasticsearch.md) -- Adapter for search and analytics.

### Brokers

- [Broker Overview](./adapters/broker/index.md) -- Unified interface for message broker implementations.
- [Inline Broker](./adapters/broker/inline.md) -- Synchronous in-memory broker for development and testing.
- [Redis Streams](./adapters/broker/redis.md) -- Durable ordered messaging with consumer groups.
- [Redis PubSub](./adapters/broker/redis-pubsub.md) -- Redis Lists-based queuing with consumer groups.
- [Custom Brokers](./adapters/broker/custom-brokers.md) -- Build your own broker adapter.

### Caches

- [Cache Overview](./adapters/cache/index.md) -- Cache providers in Protean.
- [Redis Cache](./adapters/cache/redis.md) -- Redis as a cache adapter.

### Event Stores

- [Event Store Overview](./adapters/eventstore/index.md) -- Event store options in Protean.
- [MessageDB](./adapters/eventstore/message-db.md) -- MessageDB event store adapter.

---

## Patterns & Recipes

In-depth guides for recurring patterns in domain-driven applications.
These span multiple domain elements and represent good practices that
Protean supports but does not enforce.

### Aggregate Design

- [Design Small Aggregates](./patterns/design-small-aggregates.md) -- Draw boundaries around consistency requirements, not data relationships.
- [One Aggregate Per Transaction](./patterns/one-aggregate-per-transaction.md) -- Modify one aggregate per handler; use events for cross-aggregate side effects.
- [Encapsulate State Changes](./patterns/encapsulate-state-changes.md) -- Express every state change as a named method capturing business intent.
- [Replace Primitives with Value Objects](./patterns/replace-primitives-with-value-objects.md) -- Extract strings and numbers into value objects with format rules and operations.

### Event-Driven Patterns

- [Design Events for Consumers](./patterns/design-events-for-consumers.md) -- Events carry enough context for consumers to act independently.
- [Idempotent Event Handlers](./patterns/idempotent-event-handlers.md) -- Produce the same result whether an event is processed once or many times.
- [Event Versioning and Evolution](./patterns/event-versioning-and-evolution.md) -- Evolve event schemas without breaking consumers or the event store.
- [Command Idempotency](./patterns/command-idempotency.md) -- Ensure processing the same command twice produces the same effect.
- [Coordinating Long-Running Processes](./patterns/coordinating-long-running-processes.md) -- Use a process manager to coordinate multi-step workflows across aggregates.

### Architecture & Quality

- [Organize by Domain Concept](./patterns/organize-by-domain-concept.md) -- The folder tree owns domain concepts; the framework carries layer metadata. Organize by aggregate, colocate capabilities, separate projections.
- [Validation Layering](./patterns/validation-layering.md) -- Different validation belongs at different layers: fields, value objects, invariants, handlers.
- [Thin Handlers, Rich Domain](./patterns/thin-handlers-rich-domain.md) -- Handlers orchestrate; aggregates and domain services contain all logic.
- [Testing Domain Logic in Isolation](./patterns/testing-domain-logic-in-isolation.md) -- Test aggregates and value objects directly, without infrastructure.

### Identity & Communication

- [Creating Identities Early](./patterns/creating-identities-early.md) -- Generate aggregate identities at creation, not at the database.
- [Connecting Concepts Across Bounded Contexts](./patterns/connect-concepts-across-domains.md) -- Synchronize the same real-world concept across multiple contexts.
- [Consuming Events from Other Domains](./patterns/consuming-events-from-other-domains.md) -- Subscribers as anti-corruption layers for external events.
- [Sharing Event Classes Across Domains](./patterns/sharing-event-classes-across-domains.md) -- Share schemas, not code; use contract tests for compatibility.

### Testing & Infrastructure

- [Setting Up and Tearing Down Databases for Tests](./patterns/setting-up-and-tearing-down-database-for-tests.md) -- Manage database schema and test data lifecycles separately for fast, isolated integration tests.

---

## Internals

Design reasoning and internal architecture for contributors and advanced users.

- [Internals Overview](./internals/index.md) -- What this section covers.
- [Field System](./internals/field-system.md) -- How FieldSpec translates domain vocabulary to Pydantic, and why three definition styles are supported.
- [Shadow Fields](./internals/shadow-fields.md) -- How ValueObject and Reference fields are flattened into database columns via shadow fields.
- [Query System](./internals/query-system.md) -- How the Repository → DAO → QuerySet → Provider chain works, Q object expression trees, lookup resolution, and lazy evaluation.

---

## Migration

- [Migrating to 0.15](./migration/v0-15.md) -- Upgrade guide for the Pydantic v2 foundation release. Covers breaking changes, field style migration, and new features.

---

## Reference

- [Glossary](./glossary.md) -- Definitions of key terms.
- [Philosophy & Design Principles](./core-concepts/philosophy.md) -- The convictions that guide Protean's design.

---

## Community

- [Community](./community/index.md) -- Get help and connect with other Protean users.
- [Development Setup](./community/contributing/setup.md) -- Set up Protean locally for contributing.
- [Testing Protean](./community/contributing/testing.md) -- Test strategy, fixtures, and running the suite.
- [Building Adapters](./community/contributing/adapters.md) -- Guidelines for creating custom adapters.
