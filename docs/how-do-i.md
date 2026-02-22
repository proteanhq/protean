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
| Add typed attributes to domain objects          | [Fields](./guides/domain-definition/fields/index.md) |
| Choose between field definition styles          | [Defining Fields](./guides/domain-definition/fields/defining-fields.md) |
| Define a domain event                           | [Events](./guides/domain-definition/events.md) |
| Understand field arguments and options          | [Arguments](./guides/domain-definition/fields/arguments.md) |
| Use simple scalar fields (String, Integer...)   | [Simple Fields](./guides/domain-definition/fields/simple-fields.md) |
| Use container fields (List, Dict, Nested)       | [Container Fields](./guides/domain-definition/fields/container-fields.md) |
| Use association fields (HasOne, HasMany, Reference) | [Association Fields](./guides/domain-definition/fields/association-fields.md) |

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
| Rebuild a projection from historical events     | [`protean projection rebuild`](./guides/cli/projection.md) |
| Listen to messages from an external broker      | [Subscribers](./guides/consume-state/subscribers.md) |

## Set Up and Configure

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Register domain elements                        | [Register Elements](./guides/compose-a-domain/register-elements.md) |
| Initialize and activate a domain                | [Initialize Domain](./guides/compose-a-domain/initialize-domain.md) |
| Configure databases, brokers, and caches        | [Configuration](./guides/essentials/configuration.md) |
| Understand identity and ID generation           | [Identity](./guides/essentials/identity.md) |
| Understand stream categories                    | [Stream Categories](./guides/essentials/stream-categories.md) |
| Activate a domain for use                       | [Activate Domain](./guides/compose-a-domain/activate-domain.md) |
| Understand element decorators                   | [Element Decorators](./guides/compose-a-domain/element-decorators.md) |
| Decide when to compose vs. initialize           | [When to Compose](./guides/compose-a-domain/when-to-compose.md) |
| Understand the object model and Meta options    | [Object Model](./guides/essentials/object-model.md) |

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
| Process events and commands asynchronously      | [Server](./guides/server/index.md) |
| Understand subscriptions and event processing   | [Subscriptions](./guides/server/subscriptions.md) |
| Use the outbox pattern for reliable messaging   | [Outbox](./guides/server/outbox.md) |
| Set up structured logging                       | [Running the Server](./guides/server/running.md#logging) |
| Add request-scoped context to logs              | [Running the Server](./guides/server/running.md#context-variables) |
| Minimize logging noise in tests                 | [Running the Server](./guides/server/running.md#test-configuration) |
| Monitor message flow in real time               | [Observability](./guides/server/observability.md) |
| Expose Prometheus metrics for the message pipeline | [Observability](./guides/server/observability.md) |
| Stream trace events via SSE                     | [Observability](./guides/server/observability.md) |
| Run the async background server                 | [`protean server`](./guides/cli/server.md) |
| Use the CLI for development and operations      | [CLI](./guides/cli/index.md) |
| Understand the server engine architecture       | [Engine](./guides/server/engine.md) |
| Learn about subscription types                  | [Subscription Types](./guides/server/subscription-types.md) |
| Configure subscriptions                         | [Server Configuration](./guides/server/configuration.md) |
| Run multiple workers with the supervisor        | [Supervisor](./guides/server/supervisor.md) |
| Use priority lanes for event processing         | [Priority Lanes](./guides/priority-lanes.md) |
| Run a bulk migration with priority lanes        | [Migration with Priority Lanes](./guides/running-migration-with-priority-lanes.md) |

## Use the CLI

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Scaffold a new Protean project                  | [`protean new`](./guides/cli/new.md) |
| Understand domain and element discovery         | [`protean` discovery](./guides/cli/discovery.md) |
| Open an interactive shell                       | [`protean shell`](./guides/cli/shell.md) |
| Run the async background server                 | [`protean server`](./guides/cli/server.md) |
| Run the observability dashboard                 | [`protean observatory`](./guides/cli/observatory.md) |
| Manage database schemas                         | [`protean db`](./guides/cli/database.md) |
| Create and manage snapshots                     | [`protean snapshot`](./guides/cli/snapshot.md) |
| Rebuild projections from events                 | [`protean projection`](./guides/cli/projection.md) |

## Evolve and Maintain

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Transform old event schemas during replay       | [Event Upcasting](./guides/event-upcasting.md) |
| Add type checking to my domain code             | [Type Checking](./guides/type-checking.md) |

## Organize My Project

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Structure my project folders by domain concept  | [Organize by Domain Concept](./patterns/organize-by-domain-concept.md) |
| Scaffold a new project with the right structure | [`protean new`](./guides/cli/new.md) |

## Choose an Architecture

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Understand the three architectural pathways     | [Choose a Path](./guides/pathways/index.md) |
| Use pure DDD with application services          | [DDD Pathway](./guides/pathways/ddd.md) |
| Separate reads and writes with CQRS             | [CQRS Pathway](./guides/pathways/cqrs.md) |
| Use event sourcing for full audit trails        | [Event Sourcing Pathway](./guides/pathways/event-sourcing.md) |
| Decide between CQRS and Event Sourcing          | [Architecture Decision](./core-concepts/architecture-decision.md) |

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
| Use PostgreSQL                                  | [PostgreSQL Adapter](./adapters/database/postgresql.md) |
| Use Elasticsearch                               | [Elasticsearch Adapter](./adapters/database/elasticsearch.md) |
| Use Redis as a message broker                   | [Redis Broker](./adapters/broker/redis.md) |
| Use Redis as a cache                            | [Redis Cache](./adapters/cache/redis.md) |
| Use Message DB as an event store                | [Message DB](./adapters/eventstore/message-db.md) |
| Build a custom broker adapter                   | [Custom Brokers](./adapters/broker/custom-brokers.md) |

## Understand Internals

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Understand how the field system works           | [Field System](./internals/field-system.md) |
| Learn why three field definition styles exist   | [Field System](./internals/field-system.md) |
| Understand how the query system works internally | [Query System](./internals/query-system.md) |
