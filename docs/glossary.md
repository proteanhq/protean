---
hide:
  - navigation
---

<!-- Show TOC on the left -->
<style>
    .md-sidebar--secondary {
        order: 0;
    }
</style>

# Glossary

A comprehensive reference of terms used throughout Protean and the patterns it implements — Domain-Driven Design, CQRS, and Event Sourcing. Terms are grouped by category and listed alphabetically within each group. Use the sidebar to jump to any term.

---

## Domain-Driven Design

### Analysis Model

A conceptual artifact that bridges the gap between the real-world domain and the software implementation. The analysis model captures the core concepts, behaviors, and rules of the domain using DDD's tactical patterns (aggregates, entities, value objects, domain services) without prescribing technological details. It is developed collaboratively by domain experts and developers and serves as a blueprint for the system's design. The goal of DDD is to keep the analysis model and the code model aligned throughout the life of the project.

[Learn more →](core-concepts/analysis-model.md) | **See also**: [Domain Model](#domain-model), [Ubiquitous Language](#ubiquitous-language)

### Aggregate

A cluster of domain objects treated as a single unit for the purpose of data changes. Every aggregate has a root entity (the *aggregate root*) that controls access to its internals and enforces business rules, guaranteeing consistency within its boundary.  In Protean, aggregates are defined with the `@domain.aggregate` decorator.

[Learn more →](guides/domain-definition/aggregates.md) | **See also**: [Aggregate Root](#aggregate-root), [Entity](#entity), [Invariant](#invariant), [Transaction Boundary](#transaction-boundary)

### Aggregate Root

The root entity of an aggregate — the single entry point through which all external interactions with the aggregate occur. The aggregate root is responsible for enforcing invariants and ensuring consistency of the entire cluster. In Protean, the class decorated with `@domain.aggregate` serves as the aggregate root.

[Learn more →](core-concepts/domain-elements/aggregates.md) | **See also**: [Aggregate](#aggregate), [Entity](#entity)

### Bounded Context

A boundary within which a particular domain model is defined and applicable. Each bounded context has its own ubiquitous language and its own set of aggregates, entities, and value objects — the same real-world concept may be modeled differently in different bounded contexts.

[Learn more →](core-concepts/ddd.md) | **See also**: [Domain](#domain), [Ubiquitous Language](#ubiquitous-language)

### Domain

The sphere of knowledge and activity around which the business logic of an application revolves. In Protean, the `Domain` class also serves as the central registry that holds all domain elements and acts as the entry point for domain operations.

[Learn more →](guides/compose-a-domain/index.md) | **See also**: [Bounded Context](#bounded-context), [Domain Model](#domain-model)

### Domain Model

The representation of core business logic and rules expressed through aggregates, entities, value objects, domain services, and events. A well-crafted domain model captures the essential complexity of the business while remaining independent of infrastructure concerns.

[Learn more →](core-concepts/ddd.md) | **See also**: [Aggregate](#aggregate), [Entity](#entity), [Value Object](#value-object)

### Entity

An object defined primarily by its identity rather than its attributes. Two entities with the same attribute values are still distinct if they have different identities. Entities are mutable and can evolve over time. In Protean, entities are defined with the `@domain.entity` decorator and exist within an aggregate boundary.

[Learn more →](guides/domain-definition/entities.md) | **See also**: [Aggregate](#aggregate), [Identity](#identity), [Value Object](#value-object)

### Ubiquitous Language

A shared vocabulary developed collaboratively by domain experts and developers, used consistently in code, conversations, and documentation. The ubiquitous language ensures that the software model accurately reflects the business domain and reduces the risk of miscommunication.

[Learn more →](core-concepts/ddd.md) | **See also**: [Bounded Context](#bounded-context), [Domain Model](#domain-model)

### Value Object

An immutable object that represents a descriptive aspect of the domain with no conceptual identity. Value objects are defined entirely by their attributes — two value objects with the same attributes are considered equal. In Protean, value objects are defined with the `@domain.value_object` decorator.

[Learn more →](guides/domain-definition/value-objects.md) | **See also**: [Entity](#entity), [Field](#field)

---

## CQRS

### Command Query Responsibility Segregation (CQRS)

A design pattern that separates the models used for reading data (queries) from the models used for writing data (commands). This separation allows each side to be optimized independently — the write model enforces business rules while the read model is denormalized for fast queries. Protean supports CQRS through distinct command/query paths and projections.

[Learn more →](core-concepts/cqrs.md) | **See also**: [Read Model](#read-model), [Write Model](#write-model), [Projection](#projection)

### Eventual Consistency

A consistency model where different parts of the system may temporarily hold different views of the data, but will converge to a consistent state over time. In Protean, eventual consistency arises when aggregates communicate through domain events processed asynchronously by event handlers or projectors.

[Learn more →](core-concepts/cqrs.md) | **See also**: [Domain Event](#domain-event), [Projection](#projection), [Transaction Boundary](#transaction-boundary)

### Query

A request to retrieve data from the system without changing state. In CQRS, queries are handled by the read model, which is optimized for the specific data access patterns required by the application's consumers.

[Learn more →](core-concepts/cqrs.md) | **See also**: [Command Query Responsibility Segregation (CQRS)](#command-query-responsibility-segregation-cqrs), [Read Model](#read-model)

### Read Model

A data model optimized for querying and reading, separate from the write model. Read models are denormalized and shaped to match specific query needs, populated by processing domain events. In Protean, projections serve as read models.

[Learn more →](core-concepts/cqrs.md) | **See also**: [Projection](#projection), [Write Model](#write-model)

### Write Model

The model responsible for handling state changes and enforcing business rules. In CQRS, the write model processes commands and ensures all invariants are satisfied before persisting changes. In Protean, the aggregate and its surrounding domain model constitute the write model.

[Learn more →](core-concepts/cqrs.md) | **See also**: [Aggregate](#aggregate), [Command](#command), [Read Model](#read-model)

---

## Event Sourcing

### Concurrency Control

A mechanism for preventing conflicts when multiple processes attempt to modify the same aggregate simultaneously. Protean uses optimistic concurrency control through aggregate versioning — each aggregate tracks a version number that is checked before persisting changes, rejecting updates based on stale versions.

[Learn more →](core-concepts/domain-elements/aggregates.md) | **See also**: [Aggregate](#aggregate), [Event Sourcing](#event-sourcing)

### Delta Event

A domain event that captures an incremental, specific change to an aggregate's state. Delta events describe *what changed* (e.g., `OrderItemAdded`, `PriceUpdated`) rather than the complete current state, making them useful for granular auditing and targeted reactions.

[Learn more →](core-concepts/domain-elements/events.md) | **See also**: [Domain Event](#domain-event), [Fact Event](#fact-event)

### Event-Carried State Transfer

A pattern where domain events carry the complete state of an aggregate, allowing consumers to build their own local copies of the data without querying the source. This pattern reduces coupling between services and improves autonomy. In Protean, fact events enable this pattern.

[Learn more →](guides/domain-definition/events.md) | **See also**: [Fact Event](#fact-event), [Projection](#projection)

### Event Sourcing

A persistence pattern in which an aggregate's state is stored as a sequence of immutable domain events rather than as a current-state snapshot. The aggregate's state at any point in time can be reconstructed by replaying its events from the beginning. In Protean, aggregates opt in with `is_event_sourced=True`.

[Learn more →](core-concepts/event-sourcing.md) | **See also**: [Event Store](#event-store), [Event Stream](#event-stream), [Replay](#replay), [Snapshot](#snapshot)

### Event Store

A specialized persistence mechanism that stores domain events as an append-only, immutable log. The event store serves as the system of record for event-sourced aggregates, providing mechanisms to append events and retrieve them by stream. Protean supports event store adapters such as Message DB.

[Learn more →](adapters/eventstore/index.md) | **See also**: [Event Sourcing](#event-sourcing), [Event Stream](#event-stream)

### Event Stream

A chronological sequence of events belonging to a specific aggregate instance. Each aggregate instance has its own event stream, identified by a combination of the stream category and the aggregate's identity. Event streams are the fundamental unit of storage in event sourcing.

[Learn more →](guides/essentials/stream-categories.md) | **See also**: [Event Store](#event-store), [Stream Category](#stream-category)

### Fact Event

A domain event that encloses the *entire* state of an aggregate at a specific point in time. Fact events are automatically generated by Protean when `fact_events=True` is set on an aggregate, and they enable the Event-Carried State Transfer pattern by providing consumers with a complete, self-contained snapshot of the aggregate.

[Learn more →](guides/domain-definition/events.md) | **See also**: [Delta Event](#delta-event), [Event-Carried State Transfer](#event-carried-state-transfer)

### Hydration

The process of reconstructing an aggregate's current state from its persisted representation. In event-sourced systems, hydration means replaying all events in the aggregate's stream. In traditional CQRS, it means loading the aggregate's current-state record from the persistence store.

[Learn more →](core-concepts/event-sourcing.md) | **See also**: [Event Sourcing](#event-sourcing), [Replay](#replay), [Snapshot](#snapshot)

### Replay

The process of reprocessing a sequence of historical events to reconstruct an aggregate's state or to rebuild a projection from scratch. Replay is a core capability of event-sourced systems, enabling debugging, auditing, and the creation of new read models from existing event history.

[Learn more →](core-concepts/event-sourcing.md) | **See also**: [Event Sourcing](#event-sourcing), [Hydration](#hydration), [Projection](#projection)

### Snapshot

A saved point-in-time representation of an aggregate's state, used to optimize hydration performance in event-sourced systems. Instead of replaying the entire event history, the system loads the most recent snapshot and only replays events that occurred after it. Protean's snapshot threshold is configurable (default: 10 events).

[Learn more →](guides/essentials/configuration.md) | **See also**: [Event Sourcing](#event-sourcing), [Hydration](#hydration)

---

## Domain Elements

### Command

An immutable message expressing the intent to perform a specific action or change the system's state. Commands are named using imperative verbs (e.g., `PlaceOrder`, `CancelReservation`) and carry the data needed to perform the requested action. In Protean, commands are defined with the `@domain.command` decorator.

[Learn more →](guides/change-state/commands.md) | **See also**: [Command Handler](#command-handler), [Domain Event](#domain-event)

### Command Handler

A component responsible for processing a command by executing the corresponding business logic on an aggregate. Each command handler is connected to a single aggregate and orchestrates the state change in response to a command. In Protean, command handlers are defined with the `@domain.command_handler` decorator.

[Learn more →](guides/change-state/command-handlers.md) | **See also**: [Command](#command), [Aggregate](#aggregate)

### Domain Event

An immutable record of something significant that happened in the domain. Events are named in past tense (e.g., `OrderPlaced`, `PaymentProcessed`) and capture the relevant data about the state change. Domain events are the primary mechanism for communication between aggregates and bounded contexts. In Protean, events are defined with the `@domain.event` decorator.

[Learn more →](guides/domain-definition/events.md) | **See also**: [Event Handler](#event-handler), [Fact Event](#fact-event), [Delta Event](#delta-event)

### Domain Service

A stateless component that encapsulates domain logic which does not naturally belong to any single aggregate, entity, or value object. Domain services typically coordinate operations that span multiple aggregates or implement complex business rules. In Protean, domain services are defined with the `@domain.domain_service` decorator.

[Learn more →](guides/domain-behavior/domain-services.md) | **See also**: [Aggregate](#aggregate), [Application Service](#application-service)

### Event Handler

A component that reacts to domain events by executing follow-up business logic. Event handlers enable decoupled, reactive behavior — they listen for specific events and perform actions such as updating other aggregates, sending notifications, or triggering external processes. In Protean, event handlers are defined with the `@domain.event_handler` decorator.

[Learn more →](guides/consume-state/event-handlers.md) | **See also**: [Domain Event](#domain-event), [Subscriber](#subscriber)

### Invariant

A business rule or constraint that must always hold true within a domain concept. Invariants are checked before and after every state change to ensure the aggregate remains in a valid state. In Protean, invariants are defined as methods decorated with `@invariant` within an aggregate or entity class.

[Learn more →](guides/domain-behavior/invariants.md) | **See also**: [Aggregate](#aggregate), [Validation](#validation)

### Projection

A read-optimized, denormalized view of data constructed by processing one or more event streams. Projections are the primary mechanism for building read models in CQRS, tailored to specific query needs. In Protean, projections are defined with the `@domain.projection` decorator.

[Learn more →](guides/consume-state/projections.md) | **See also**: [Projector](#projector), [Read Model](#read-model)

### Subscriber

A component that consumes messages from external message brokers or other systems outside the domain boundary. Subscribers bridge the gap between external messaging infrastructure and the domain's internal event handling. In Protean, subscribers are defined with the `@domain.subscriber` decorator.

[Learn more →](guides/consume-state/subscribers.md) | **See also**: [Broker](#broker), [Event Handler](#event-handler)

---

## Fields & Data

### Association Field

A field type that defines a relationship between domain elements. Protean provides three association field types: `HasOne` for one-to-one relationships, `HasMany` for one-to-many relationships, and `Reference` for establishing the inverse relationship from a child entity back to its parent aggregate.

[Learn more →](guides/domain-definition/fields/association-fields.md) | **See also**: [Field](#field), [Shadow Field](#shadow-field)

### Container Field

A field type that holds multiple or composite values. Protean provides `List` for ordered collections, `Dict` for key-value mappings, and `ValueObject` for embedding a value object directly within an entity or aggregate.

[Learn more →](guides/domain-definition/fields/container-fields.md) | **See also**: [Field](#field), [Value Object](#value-object)

### Field

The fundamental building block for defining the structure and data types of domain elements. Fields are implemented as Python descriptors and handle type validation, constraints, and defaults. Protean provides simple fields (String, Integer, Float, Boolean, Date, DateTime, etc.), container fields, and association fields.

[Learn more →](guides/domain-definition/fields/index.md) | **See also**: [Simple Field](#simple-field), [Container Field](#container-field), [Association Field](#association-field)

### Identity

A unique identifier that distinguishes one entity or aggregate instance from all others. In Protean, identity can be configured through identity strategies (`uuid`, `function`), identity types (`string`, `integer`, `uuid`), and custom identifier fields.

[Learn more →](guides/essentials/identity.md) | **See also**: [Entity](#entity), [Aggregate](#aggregate)

### Shadow Field

A hidden field automatically created alongside a `Reference` association field. The shadow field stores the actual identifier value (the foreign key) linking a child entity to its parent aggregate. Shadow fields are named with a `_id` suffix by convention.

[Learn more →](guides/domain-definition/relationships.md) | **See also**: [Association Field](#association-field), [Identity](#identity)

### Simple Field

A basic field type for scalar data values. Protean's simple fields include `String`, `Text`, `Integer`, `Float`, `Boolean`, `Date`, `DateTime`, `Auto` (auto-generated identities), and `Identifier` (explicit identity fields).

[Learn more →](guides/domain-definition/fields/simple-fields.md) | **See also**: [Field](#field), [Identity](#identity)

### Validation

The process of ensuring data conforms to defined constraints and business rules. Protean supports field-level validation (type checks, required fields, max length, allowed values) and domain-level validation through invariants. Custom validators can be attached to individual fields for domain-specific constraints.

[Learn more →](guides/domain-behavior/validations.md) | **See also**: [Field](#field), [Invariant](#invariant)

---

## Application Layer

### Application Service

A service that orchestrates a specific business use case by coordinating between the domain model and infrastructure. Application services receive commands, load aggregates from repositories, invoke domain logic, and persist the results. In Protean, application services are defined with the `@domain.application_service` decorator.

[Learn more →](guides/change-state/application-services.md) | **See also**: [Command Handler](#command-handler), [Domain Service](#domain-service), [Repository](#repository)

### Composition

The process of assembling a domain by registering its elements — aggregates, entities, value objects, commands, events, handlers, and services — into the `Domain` registry. In Protean, elements are auto-discovered from specified modules or manually registered, then wired together during domain initialization.

[Learn more →](guides/compose-a-domain/index.md) | **See also**: [Domain](#domain)

### Custom Repository

A repository with user-defined methods that go beyond standard CRUD operations, tailored to specific aggregate access patterns. Custom repositories allow encapsulating complex queries and domain-specific data access logic while maintaining the abstraction boundary. In Protean, custom repositories are defined with the `@domain.repository` decorator.

[Learn more →](guides/change-state/retrieve-aggregates.md) | **See also**: [Repository](#repository), [Data Access Object (DAO)](#data-access-object-dao)

### Database Model

A persistence-technology-specific data schema that maps domain elements to their storage representation. Database models handle the translation between domain objects and the underlying storage format (relational tables, document structures, etc.). In Protean, database models are defined with the `@domain.model` decorator.

[Learn more →](guides/change-state/persist-aggregates.md) | **See also**: [Repository](#repository), [Provider](#provider)

### Projector

A specialized handler responsible for keeping projections up to date by listening to domain events and applying the corresponding changes to projection data. Projectors work exclusively with projections, translating domain events into read model updates. In Protean, projectors are defined with the `@domain.projector` decorator.

[Learn more →](guides/consume-state/projections.md) | **See also**: [Projection](#projection), [Event Handler](#event-handler)

### Repository

An abstraction that encapsulates the storage, retrieval, and search behavior for aggregates. Repositories provide a collection-like interface that isolates domain logic from the details of data storage, allowing the persistence mechanism to be swapped without affecting the domain model.

[Learn more →](guides/change-state/persist-aggregates.md) | **See also**: [Aggregate](#aggregate), [Custom Repository](#custom-repository), [Unit of Work](#unit-of-work)

### Unit of Work

A pattern that groups all changes made to aggregates within a single business operation into an atomic transaction. The unit of work tracks changes, coordinates persistence, and ensures that either all changes are committed or none are. In Protean, the unit of work is managed automatically via a context manager.

[Learn more →](guides/change-state/unit-of-work.md) | **See also**: [Repository](#repository), [Transaction Boundary](#transaction-boundary)

---

## Reactive Layer

### Event-Driven Architecture

An architectural style in which the flow of the program is determined by events — significant state changes that are published and consumed asynchronously. Components communicate by producing and reacting to events rather than through direct calls, promoting loose coupling and scalability. Protean's reactive layer is built on this principle.

[Learn more →](core-concepts/event-sourcing.md) | **See also**: [Domain Event](#domain-event), [Event Handler](#event-handler), [Eventual Consistency](#eventual-consistency)

### Stream Category

A logical name that groups related message streams together. Stream categories serve as the routing mechanism for subscriptions, determining which handlers receive which messages. In Protean, stream categories are derived from the aggregate class name by default and can be customized via the `stream_category` meta option.

[Learn more →](guides/essentials/stream-categories.md) | **See also**: [Event Stream](#event-stream), [Subscription](#subscription)

---

## Infrastructure

### Adapter

A concrete implementation of a port that connects the domain to a specific technology. Adapters translate between the domain's abstract interfaces and the details of external systems (databases, message brokers, caches). Protean ships with adapters for PostgreSQL, Elasticsearch, Redis, Message DB, and more.

[Learn more →](adapters/index.md) | **See also**: [Port](#port), [Ports and Adapters Architecture](#ports-and-adapters-architecture)

### Broker

A message broker infrastructure component responsible for publishing and delivering messages (events and commands) between producers and consumers. Protean supports multiple broker implementations including an inline (in-process) broker for development and Redis-based brokers for production.

[Learn more →](adapters/broker/index.md) | **See also**: [Adapter](#adapter), [Subscriber](#subscriber)

### Cache

A caching infrastructure component for storing frequently accessed data to reduce load on primary data stores and improve response times. In Protean, caches are configured as adapters and can be backed by implementations such as Redis.

[Learn more →](adapters/cache/index.md) | **See also**: [Adapter](#adapter), [Provider](#provider)

### Data Access Object (DAO)

A pattern that provides a low-level abstract interface for database operations. In Protean, the DAO layer sits beneath repositories and handles the direct interaction with persistence technologies, allowing repositories to remain technology-agnostic.

[Learn more →](adapters/database/index.md) | **See also**: [Repository](#repository), [Provider](#provider)

### Event Store Adapter

An adapter implementation for persisting and retrieving domain events. Event store adapters provide the concrete storage mechanism for event sourcing, supporting operations like appending events, reading streams, and managing snapshots. Protean includes a Message DB adapter for production use.

[Learn more →](adapters/eventstore/index.md) | **See also**: [Event Store](#event-store), [Adapter](#adapter)

### Outbox Pattern

A reliability pattern that ensures messages are published to the broker exactly when the associated business transaction commits. Events are first written to an outbox table in the same database transaction as the aggregate changes, then asynchronously picked up and published to the broker by a background processor.

[Learn more →](guides/server/outbox.md) | **See also**: [Broker](#broker), [Transaction Boundary](#transaction-boundary), [Unit of Work](#unit-of-work)

### Port

An abstract interface that defines the contract between the domain and external infrastructure. Ports specify *what* capabilities are needed (persistence, messaging, caching) without prescribing *how* they are implemented. In Protean, ports include `BaseProvider`, `BaseBroker`, `BaseEventStore`, and `BaseCache`.

[Learn more →](adapters/internals.md) | **See also**: [Adapter](#adapter), [Ports and Adapters Architecture](#ports-and-adapters-architecture)

### Ports and Adapters Architecture

An architectural pattern (also known as Hexagonal Architecture) that isolates the domain model from technology concerns. The domain defines ports (abstract interfaces) for its infrastructure needs, and adapters provide concrete implementations. This separation allows swapping technologies without changing domain logic.

[Learn more →](adapters/index.md) | **See also**: [Adapter](#adapter), [Port](#port)

### Provider

A database adapter that provides persistence functionality for a specific storage technology. Providers handle connection management, query execution, and data mapping. In Protean, providers can be assigned per aggregate using the `provider` meta option, allowing different aggregates to use different databases.

[Learn more →](guides/essentials/configuration.md) | **See also**: [Adapter](#adapter), [Database Model](#database-model)

---

## Server & Messaging

### Consumer Group

A mechanism that allows multiple instances of an application to process messages from the same stream in parallel, with each message delivered to exactly one consumer in the group. Consumer groups provide automatic load balancing and fault tolerance. In Protean, consumer groups are used by `StreamSubscription` via Redis Streams.

[Learn more →](guides/server/subscription-types.md) | **See also**: [Subscription](#subscription), [Engine](#engine)

### Dead Letter Queue

A dedicated stream where messages that have failed processing after exhausting all retry attempts are moved. Dead letter queues preserve failed messages along with error metadata, enabling debugging, analysis, and manual reprocessing.

[Learn more →](guides/server/subscription-types.md) | **See also**: [Subscription](#subscription), [Idempotency](#idempotency)

### CommandDispatcher

An internal routing mechanism that consolidates multiple command handler subscriptions on the same stream category into a single subscription. Instead of creating N separate subscriptions that compete for the same messages, the engine creates one `CommandDispatcher` per stream category that reads each command once and routes it to the correct handler based on the command type.

[Learn more →](guides/server/engine.md) | **See also**: [Command Handler](#command-handler), [Engine](#engine), [Subscription](#subscription)

### Engine

The core async message processing system in Protean that manages the lifecycle of subscriptions, coordinates message handling, and provides graceful startup and shutdown. The engine polls for messages from event stores and brokers, delivers them to the appropriate handlers, and tracks processing state.

[Learn more →](guides/server/engine.md) | **See also**: [Subscription](#subscription), [Broker](#broker)

### Idempotency

The property ensuring that processing the same message multiple times produces the same result as processing it once. Idempotent handlers are essential in distributed systems where messages may be delivered more than once due to retries, network issues, or at-least-once delivery guarantees.

[Learn more →](core-concepts/domain-elements/command-handlers.md) | **See also**: [Command Handler](#command-handler), [Event Handler](#event-handler)

### Message

A piece of data transmitted between components in an event-driven system. In Protean, messages are the supertype encompassing both commands (requests to do something) and domain events (records of something that happened). Messages flow through streams and are processed by handlers.

[Learn more →](guides/essentials/stream-categories.md) | **See also**: [Command](#command), [Domain Event](#domain-event), [Stream Category](#stream-category)

### MessageTrace

A structured dataclass representing one stage of a message's journey through the processing pipeline. Each trace captures the event type, domain, stream, message identity, status, handler name, processing duration, and optional error and metadata. MessageTrace events are serialized to JSON and published to Redis Pub/Sub by the TraceEmitter.

[Learn more →](guides/server/observability.md) | **See also**: [TraceEmitter](#traceemitter), [Observatory](#observatory)

### Observatory

A standalone FastAPI server (`Observatory`) that provides real-time monitoring of the Protean message processing pipeline. It subscribes to the trace event channel and exposes an HTML dashboard, Server-Sent Events stream, REST API for infrastructure health and statistics, and a Prometheus metrics endpoint. Runs on its own port (default 9000), separate from the application.

[Learn more →](guides/server/observability.md) | **See also**: [TraceEmitter](#traceemitter), [MessageTrace](#messagetrace), [Engine](#engine)

### Position Tracking

The mechanism by which subscriptions track which messages have been successfully processed. Position tracking ensures that after a restart, a subscription resumes from where it left off rather than reprocessing the entire stream. Different subscription types implement position tracking differently (cursor-based, consumer group ACKs, etc.).

[Learn more →](guides/server/subscriptions.md) | **See also**: [Subscription](#subscription), [Consumer Group](#consumer-group)

### Subscription

A long-running process that connects message sources (event stores or brokers) to handlers. Subscriptions manage the message flow lifecycle: polling for new messages, delivering them to handlers, tracking processed positions, and handling errors with retries. Protean provides `StreamSubscription`, `EventStoreSubscription`, and `BrokerSubscription` types.

[Learn more →](guides/server/subscriptions.md) | **See also**: [Engine](#engine), [Stream Category](#stream-category), [Position Tracking](#position-tracking)

### TraceEmitter

A lightweight component attached to the Engine that publishes structured `MessageTrace` events to Redis Pub/Sub as messages flow through the processing pipeline. Designed for zero overhead when nobody is listening — it checks subscriber count via `PUBSUB NUMSUB` and short-circuits before any serialization when no subscribers are found. Tracing failures are silently swallowed and never affect message processing.

[Learn more →](guides/server/observability.md) | **See also**: [MessageTrace](#messagetrace), [Observatory](#observatory), [Engine](#engine)

### Transaction Boundary

The scope within which all state changes must be atomic — either all succeed or all are rolled back. In domain-driven design, each aggregate defines a transaction boundary. No single transaction should span multiple aggregates; cross-aggregate consistency is achieved through eventual consistency via domain events.

[Learn more →](guides/change-state/unit-of-work.md) | **See also**: [Aggregate](#aggregate), [Unit of Work](#unit-of-work), [Eventual Consistency](#eventual-consistency)

---

## Testing

### Domain Model Testing

The practice of testing domain logic in isolation from infrastructure, using plain Python objects without mocks. Because Protean's domain model is technology-agnostic, aggregates, entities, value objects, and domain services can be tested directly by constructing them, invoking their methods, and asserting on their state.

[Learn more →](guides/testing/domain-model-tests.md) | **See also**: [Domain Model](#domain-model), [Test Mode](#test-mode)

### Test Mode

A configuration setting for the Protean engine that enables deterministic, synchronous message processing suitable for automated tests. In test mode, exceptions are propagated rather than handled by retry logic, making test failures immediately visible and debuggable.

[Learn more →](guides/testing/index.md) | **See also**: [Engine](#engine), [Domain Model Testing](#domain-model-testing)
