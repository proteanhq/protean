# How Do I...?

A task-oriented index into the Protean documentation. Find the guide you
need by what you're trying to accomplish.

## Model My Domain

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Define a root entity with business logic        | [Aggregates](./domain-definition/aggregates.md) |
| Add a child object with identity to an aggregate | [Entities](./domain-definition/entities.md) |
| Create an immutable descriptive value (Money, Email, Address) | [Value Objects](./domain-definition/value-objects.md) |
| Choose between an entity and a value object     | [Deciding Between Elements](./domain-definition/deciding-between-elements.md) |
| Connect entities with relationships             | [Relationships](./domain-definition/relationships.md) |
| Add typed attributes to domain objects          | [Fields](./domain-definition/fields/index.md) |
| Define a domain event                           | [Events](./domain-definition/events.md) |

## Add Business Rules

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Validate field values                           | [Validations](./domain-behavior/validations.md) |
| Enforce business invariants                     | [Invariants](./domain-behavior/invariants.md) |
| Change aggregate state safely                   | [Aggregate Mutation](./domain-behavior/aggregate-mutation.md) |
| Raise domain events from an aggregate           | [Raising Events](./domain-behavior/raising-events.md) |
| Coordinate logic across multiple aggregates     | [Domain Services](./domain-behavior/domain-services.md) |

## Handle Requests and Change State

| I want to...                                    | Guide | Pathway |
|-------------------------------------------------|-------|---------|
| Handle a user request synchronously             | [Application Services](./change-state/application-services.md) | DDD |
| Define a command representing user intent       | [Commands](./change-state/commands.md) | CQRS, ES |
| Process a command and update an aggregate       | [Command Handlers](./change-state/command-handlers.md) | CQRS, ES |
| Save an aggregate to the database               | [Persist Aggregates](./change-state/persist-aggregates.md) | All |
| Load an aggregate by ID or query                | [Retrieve Aggregates](./change-state/retrieve-aggregates.md) | All |
| Manage transactions                             | [Unit of Work](./change-state/unit-of-work.md) | All |

## React to State Changes

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Run side effects when an event fires            | [Event Handlers](./consume-state/event-handlers.md) |
| Build a read-optimized view from events         | [Projections](./consume-state/projections.md) |
| Listen to messages from an external broker      | [Subscribers](./consume-state/subscribers.md) |

## Set Up and Configure

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Register domain elements                        | [Register Elements](./compose-a-domain/register-elements.md) |
| Initialize and activate a domain                | [Initialize Domain](./compose-a-domain/initialize-domain.md) |
| Configure databases, brokers, and caches        | [Configuration](./essentials/configuration.md) |
| Understand identity and ID generation           | [Identity](./essentials/identity.md) |
| Understand stream categories                    | [Stream Categories](./essentials/stream-categories.md) |

## Run in Production

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Process events and commands asynchronously      | [Server](./server/index.md) |
| Understand subscriptions and event processing   | [Subscriptions](./server/subscriptions.md) |
| Use the outbox pattern for reliable messaging   | [Outbox](./server/outbox.md) |
| Use the CLI for development and operations      | [CLI](./cli/index.md) |

## Choose an Architecture

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Understand the three architectural pathways     | [Choose a Path](./pathways/index.md) |
| Use pure DDD with application services          | [DDD Pathway](./pathways/ddd.md) |
| Separate reads and writes with CQRS             | [CQRS Pathway](./pathways/cqrs.md) |
| Use event sourcing for full audit trails        | [Event Sourcing Pathway](./pathways/event-sourcing.md) |
| Decide between CQRS and Event Sourcing          | [Architecture Decision](../core-concepts/architecture-decision.md) |

## Test My Code

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Test domain model logic                         | [Domain Model Tests](./testing/domain-model-tests.md) |
| Test application workflows (BDD-style)          | [Application Tests](./testing/application-tests.md) |
| Test with real databases and brokers             | [Integration Tests](./testing/integration-tests.md) |
| Set up test fixtures and patterns               | [Fixtures and Patterns](./testing/fixtures-and-patterns.md) |

## Use Specific Technologies

| I want to...                                    | Guide |
|-------------------------------------------------|-------|
| Use PostgreSQL                                  | [PostgreSQL Adapter](../adapters/database/postgresql.md) |
| Use Elasticsearch                               | [Elasticsearch Adapter](../adapters/database/elasticsearch.md) |
| Use Redis as a message broker                   | [Redis Broker](../adapters/broker/redis.md) |
| Use Redis as a cache                            | [Redis Cache](../adapters/cache/redis.md) |
| Use Message DB as an event store                | [Message DB](../adapters/eventstore/message-db.md) |
| Build a custom broker adapter                   | [Custom Brokers](../adapters/broker/custom-brokers.md) |
