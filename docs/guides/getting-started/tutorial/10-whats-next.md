# Chapter 10: What Comes Next

We have built a working bookstore with aggregates, value objects, entities,
commands, events, projections, a real database, and tests. Here is where
to go from here.

## Application Services

Coordinate use cases from an API layer with synchronous request-response.
See [Application Services](../../change-state/application-services.md).

## Domain Services

Orchestrate business logic that spans multiple aggregates — like checking
inventory before fulfilling an order.
See [Domain Services](../../domain-behavior/domain-services.md).

## Async Processing and the Server

Run event handlers and command handlers in a background process using
message brokers. See the [Server guide](../../../concepts/async-processing/index.md).

## Event Sourcing

Store events instead of state for full audit trails and temporal queries.
See the [Event Sourcing pathway](../../pathways/event-sourcing.md).

## Multiple Databases

Use PostgreSQL for aggregates and Elasticsearch for projections —
configured per element. See [Configuration](../../../reference/configuration/index.md).

## Subscribers

Process messages from external systems using the anti-corruption layer
pattern. See [Subscribers](../../consume-state/subscribers.md).

## API Endpoints

Expose your domain through FastAPI endpoints that translate HTTP requests
into commands. See [FastAPI Integration](../../fastapi/index.md).

## Continue Learning

- **[Guides](../../compose-a-domain/index.md)** — deep dives into each
  concept
- **[Architecture](../../../concepts/architecture/ddd.md)** — DDD, CQRS, and
  Event Sourcing theory
- **[Adapters](../../../reference/adapters/index.md)** — database, broker, cache,
  and event store adapters
- **[Patterns](../../../patterns/index.md)** — aggregate sizing,
  idempotent handlers, validation layering, and more
- **[CLI](../../../reference/cli/index.md)** — all command-line tools
