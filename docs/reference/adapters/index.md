# Adapters

Protean provides adapters for four infrastructure ports. Each port ships with
an in-memory adapter that is active by default.

For an understanding of the ports and adapters architecture and how it fits
into Protean's design, see
[Ports & Adapters](../../concepts/ports-and-adapters/index.md).

## Database

The [Database port](./database/index.md) defines the interface for interacting
with persistent storage
systems. It abstracts the underlying database technology, allowing Protean to
support various databases without changing the core application logic.

Current Implementations:

- [PostgreSQL](./database/postgresql.md)
- [Elasticsearch](./database/elasticsearch.md)

## Broker

The [Broker port](./broker/index.md) defines the interface for message brokers and pub/sub systems.
It enables communication between different parts of the ecosystem via messages,
facilitating asynchronous processing and decoupling.

!!!note
    Protean internally uses an Event Store that acts both as an event
    storage mechanism as well as a message delivery mechanism within a Protean-based
    application. Brokers are more focused on integration with other systems.

Current Implementations:

- [Inline](./broker/inline.md) - In-memory broker for development and testing
- [Redis Streams](./broker/redis.md) - Durable message streaming with consumer groups
- [Redis PubSub](./broker/redis-pubsub.md) - Simple queuing with Redis Lists

Learn more:

- [Broker Capabilities](./broker/index.md#broker-capabilities) - Understanding what each broker can do
- [Custom Brokers](./broker/custom-brokers.md) - Create your own broker adapters

## Cache

The [Cache port](./cache/index.md) defines the interface for interacting with caching systems. It
exposes APIs to temporarily store and retrieve data, improving application
performance by reducing the need for repeated database access.

Current Implementations:

- [Redis](./cache/redis.md)

## Event Store

The [Event Store](./eventstore/index.md) port defines the interface for event sourcing and event store
systems. It handles the storage and retrieval of events, which are the
fundamental units of change in event-driven architectures. This port ensures
that all state changes are recorded as a sequence of events, providing a
complete audit trail and enabling features like event replay and temporal
queries.

Current Implementations:

- [Message DB](./eventstore/message-db.md)

!!!note
    We are working on adding a comprehensive set of adapters to this list.
    We welcome your contribution - head over to the section on
    [contributing adapters](../../community/contributing/adapters.md) for more
    information.

    You can sponsor an adapter if you want to fast-track its implementation.
    [Get in touch](mailto:sponsor@ambitious.systems) with us for a discussion.
