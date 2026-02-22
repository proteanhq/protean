# How Do I...?

A task-oriented index into the Protean documentation. Find the guide you
need by what you're trying to accomplish.

## Model My Domain

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Define a root entity with business logic        | [Aggregates](./guides/domain-definition/aggregates.md) |
| Add a child object with identity to an aggregate | [Entities](./guides/domain-definition/entities.md) |
| Create an immutable descriptive value (Money, Email, Address) | [Value Objects](./guides/domain-definition/value-objects.md) |
| Choose between an entity and a value object     | [Deciding Between Elements](./guides/domain-definition/deciding-between-elements.md) |
| Connect entities with relationships             | [Relationships](./guides/domain-definition/relationships.md) |
| Add typed attributes to domain objects          | [Fields](./reference/fields/index.md) |
| Choose between field definition styles          | [Defining Fields](./reference/fields/defining-fields.md) |
| Define a domain event                           | [Events](./guides/domain-definition/events.md) |
| Understand field arguments and options          | [Arguments](./reference/fields/arguments.md) |
| Use simple scalar fields (String, Integer...)   | [Simple Fields](./reference/fields/simple-fields.md) |
| Use container fields (List, Dict, Nested)       | [Container Fields](./reference/fields/container-fields.md) |
| Use association fields (HasOne, HasMany, Reference) | [Association Fields](./reference/fields/association-fields.md) |

## Add Business Rules

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Validate field values                           | [Validations](./guides/domain-behavior/validations.md) |
| Enforce business invariants                     | [Invariants](./guides/domain-behavior/invariants.md) |
| Change aggregate state safely                   | [Aggregate Mutation](./guides/domain-behavior/aggregate-mutation.md) |
| Raise domain events from an aggregate           | [Raising Events](./guides/domain-behavior/raising-events.md) |
| Coordinate logic across multiple aggregates     | [Domain Services](./guides/domain-behavior/domain-services.md) |

## Handle Requests and Change State

| I want to...                                    | Guide | Pathway |
|-------------------------------------------------|-------|---------|
| Handle a user request synchronously             | [Application Services](./guides/change-state/application-services.md) | DDD |
| Define a command representing user intent       | [Commands](./guides/change-state/commands.md) | CQRS, ES |
| Process a command and update an aggregate       | [Command Handlers](./guides/change-state/command-handlers.md) | CQRS, ES |
| Save an aggregate to the database               | [Persist Aggregates](./guides/change-state/persist-aggregates.md) | All |
| Load an aggregate by ID or query                | [Retrieve Aggregates](./guides/change-state/retrieve-aggregates.md) | All |
| Load an aggregate at a specific version or time | [Temporal Queries](./guides/change-state/temporal-queries.md) | ES |
| Define a custom repository with domain queries  | [Repositories](./guides/change-state/repositories.md) | All |
| Query aggregates with complex filters            | [Retrieve Aggregates](./guides/change-state/retrieve-aggregates.md) | All |
| Paginate query results                           | [Retrieve Aggregates](./guides/change-state/retrieve-aggregates.md) | All |
| Use Q objects for AND/OR/NOT queries             | [Retrieve Aggregates](./guides/change-state/retrieve-aggregates.md) | All |
| Perform bulk updates or deletes                  | [Retrieve Aggregates](./guides/change-state/retrieve-aggregates.md) | All |
| Manage transactions                             | [Unit of Work](./guides/change-state/unit-of-work.md) | All |

## React to State Changes

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Run side effects when an event fires            | [Event Handlers](./guides/consume-state/event-handlers.md) |
| Coordinate a multi-step process across aggregates | [Process Managers](./guides/consume-state/process-managers.md) |
| Correlate events to a running process           | [Process Managers](./guides/consume-state/process-managers.md) |
| Build a read-optimized view from events         | [Projections](./guides/consume-state/projections.md) |
| Rebuild a projection from historical events     | [`protean projection rebuild`](./reference/cli/data/projection.md) |
| Listen to messages from an external broker      | [Subscribers](./guides/consume-state/subscribers.md) |

## Set Up and Configure

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Register domain elements                        | [Register Elements](./guides/compose-a-domain/register-elements.md) |
| Initialize and activate a domain                | [Initialize Domain](./guides/compose-a-domain/initialize-domain.md) |
| Configure databases, brokers, and caches        | [Configuration](./reference/configuration/index.md) |
| Understand identity and ID generation           | [Identity](./reference/domain-elements/identity.md) |
| Understand stream categories                    | [Stream Categories](./concepts/async-processing/stream-categories.md) |
| Activate a domain for use                       | [Activate Domain](./guides/compose-a-domain/activate-domain.md) |
| Understand element decorators                   | [Element Decorators](./reference/domain-elements/element-decorators.md) |
| Decide when to compose vs. initialize           | [When to Compose](./guides/compose-a-domain/when-to-compose.md) |
| Understand the object model and Meta options    | [Object Model](./reference/domain-elements/object-model.md) |

## Integrate with FastAPI

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Push domain context per HTTP request            | [FastAPI Integration](./guides/fastapi/index.md) |
| Map URL prefixes to different domains           | [FastAPI Integration](./guides/fastapi/index.md#domain-context-middleware) |
| Map Protean exceptions to HTTP error responses  | [FastAPI Integration](./guides/fastapi/index.md#exception-handlers) |
| Use a custom resolver for domain routing        | [FastAPI Integration](./guides/fastapi/index.md#custom-resolver) |

## Run in Production

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Process events and commands asynchronously      | [Server](./concepts/async-processing/index.md) |
| Understand subscriptions and event processing   | [Subscriptions](./concepts/async-processing/subscriptions.md) |
| Use the outbox pattern for reliable messaging   | [Outbox](./concepts/async-processing/outbox.md) |
| Set up structured logging                       | [Running the Server](./guides/server/index.md#logging) |
| Add request-scoped context to logs              | [Running the Server](./guides/server/index.md#context-variables) |
| Minimize logging noise in tests                 | [Running the Server](./guides/server/index.md#test-configuration) |
| Monitor message flow in real time               | [Observability](./reference/server/observability.md) |
| Expose Prometheus metrics for the message pipeline | [Observability](./reference/server/observability.md) |
| Stream trace events via SSE                     | [Observability](./reference/server/observability.md) |
| Run the async background server                 | [`protean server`](./reference/cli/runtime/server.md) |
| Use the CLI for development and operations      | [CLI](./reference/cli/index.md) |
| Understand the server engine architecture       | [Engine](./concepts/async-processing/engine.md) |
| Learn about subscription types                  | [Subscription Types](./reference/server/subscription-types.md) |
| Configure subscriptions                         | [Server Configuration](./reference/server/configuration.md) |
| Run multiple workers with the supervisor        | [Supervisor](./reference/server/supervisor.md) |
| Use priority lanes for event processing         | [Priority Lanes](./concepts/async-processing/priority-lanes.md) |
| Run a bulk migration with priority lanes        | [Migration with Priority Lanes](./patterns/running-migration-with-priority-lanes.md) |

## Use the CLI

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Scaffold a new Protean project                  | [`protean new`](./reference/cli/project/new.md) |
| Understand domain and element discovery         | [`protean` discovery](./reference/cli/project/discovery.md) |
| Open an interactive shell                       | [`protean shell`](./reference/cli/project/shell.md) |
| Run the async background server                 | [`protean server`](./reference/cli/runtime/server.md) |
| Run the observability dashboard                 | [`protean observatory`](./reference/cli/runtime/observatory.md) |
| Manage database schemas                         | [`protean db`](./reference/cli/data/database.md) |
| Create and manage snapshots                     | [`protean snapshot`](./reference/cli/data/snapshot.md) |
| Rebuild projections from events                 | [`protean projection`](./reference/cli/data/projection.md) |
| Inspect events in the event store               | [`protean events`](./reference/cli/data/events.md) |
| View the event history of an aggregate          | [`protean events history`](./reference/cli/data/events.md) |

## Evolve and Maintain

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Transform old event schemas during replay       | [Event Upcasting](./guides/consume-state/event-upcasting.md) |
| Add type checking to my domain code             | [Type Checking](./reference/type-checking/index.md) |

## Organize My Project

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Structure my project folders by domain concept  | [Organize by Domain Concept](./patterns/organize-by-domain-concept.md) |
| Scaffold a new project with the right structure | [`protean new`](./reference/cli/project/new.md) |

## Choose an Architecture

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Understand the three architectural pathways     | [Choose a Path](./guides/pathways/index.md) |
| Use pure DDD with application services          | [DDD Pathway](./guides/pathways/ddd.md) |
| Separate reads and writes with CQRS             | [CQRS Pathway](./guides/pathways/cqrs.md) |
| Use event sourcing for full audit trails        | [Event Sourcing Pathway](./guides/pathways/event-sourcing.md) |
| Decide between CQRS and Event Sourcing          | [Architecture Decision](./concepts/architecture/architecture-decision.md) |

## Test My Code

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Test domain model logic                         | [Domain Model Tests](./guides/testing/domain-model-tests.md) |
| Test application workflows (BDD-style)          | [Application Tests](./guides/testing/application-tests.md) |
| Test event-sourced aggregates with a fluent DSL | [Event Sourcing Tests](./guides/testing/event-sourcing-tests.md) |
| Test with real databases and brokers             | [Integration Tests](./guides/testing/integration-tests.md) |
| Set up test fixtures and patterns               | [Fixtures and Patterns](./guides/testing/fixtures-and-patterns.md) |
| Set up databases for integration tests          | [Database Setup/Teardown](./patterns/setting-up-and-tearing-down-database-for-tests.md) |

## Use Specific Technologies

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Use PostgreSQL                                  | [PostgreSQL Adapter](./reference/adapters/database/postgresql.md) |
| Use Elasticsearch                               | [Elasticsearch Adapter](./reference/adapters/database/elasticsearch.md) |
| Use Redis as a message broker                   | [Redis Broker](./reference/adapters/broker/redis.md) |
| Use Redis as a cache                            | [Redis Cache](./reference/adapters/cache/redis.md) |
| Use Message DB as an event store                | [Message DB](./reference/adapters/eventstore/message-db.md) |
| Build a custom broker adapter                   | [Custom Brokers](./reference/adapters/broker/custom-brokers.md) |

## Understand Internals

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Understand how the field system works           | [Field System](./concepts/internals/field-system.md) |
| Learn why three field definition styles exist   | [Field System](./concepts/internals/field-system.md) |
| Understand how the query system works internally | [Query System](./concepts/internals/query-system.md) |
