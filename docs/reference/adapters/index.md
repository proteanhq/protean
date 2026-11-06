# Adapters

Protean provides adapters for four infrastructure ports. Each port ships with
an in-memory adapter that is active by default.

For an understanding of the ports and adapters architecture and how it fits
into Protean's design, see
[Ports & Adapters](../../concepts/ports-and-adapters/index.md).

## Database

The [Database port](./database/index.md) defines the interface for interacting
with persistent storage systems. It abstracts the underlying database
technology, allowing Protean to support various databases without changing the
core application logic.

Each provider declares its [capabilities](./database/index.md#database-capabilities),
enabling capability-gated methods and automatic test selection.

Current implementations:

- [Memory](./database/memory.md): The default in-memory provider, with no external dependencies.
- [SQLite](./database/sqlite.md): A file-based relational provider.
- [PostgreSQL](./database/postgresql.md): A full-capability relational provider.
- [MySQL](./database/mysql.md): MySQL and MariaDB, over SQLAlchemy and PyMySQL.
- [MSSQL](./database/mssql.md): Microsoft SQL Server, over SQLAlchemy and pyodbc.
- [Elasticsearch](./database/elasticsearch.md): A document store for search and analytics.

Learn more:

- [Database capabilities](./database/index.md#database-capabilities): What each provider can do.
- [Custom database adapters](./database/custom-databases.md): Writing your own.

## Broker

The [Broker port](./broker/index.md) defines the interface for message brokers
and pub/sub systems. A broker carries messages between different parts of the
ecosystem. Those parts can then process messages asynchronously and stay
decoupled from each other.

!!!note
    Protean internally uses an Event Store that acts both as an event
    storage mechanism as well as a message delivery mechanism within a
    Protean-based application. Brokers are more focused on integration with
    other systems.

Current Implementations:

- [Inline](./broker/inline.md): In-memory broker for development and testing
- [Redis Streams](./broker/redis.md): Durable message streaming with consumer groups
- [Redis PubSub](./broker/redis-pubsub.md): Simple queuing with Redis Lists

Learn more:

- [Broker Capabilities](./broker/index.md#broker-capabilities): Understanding what each broker can do
- [Custom Brokers](./broker/custom-brokers.md): Create your own broker adapters

## Cache

The [Cache port](./cache/index.md) defines the interface for interacting with
caching systems. You use its APIs to store projection data for a limited time
and read it back. Your application then reads the database less often and runs
faster.

Current Implementations:

- Memory - Default in-memory cache (no external dependencies)
- [Redis](./cache/redis.md): Persistent distributed cache with TTL support

## Event Store

The [Event Store](./eventstore/index.md) port defines the interface for event
sourcing and event store systems. An adapter for this port stores events and
reads them back. Events are the fundamental units of change in event-driven
architectures. This port ensures that all state changes are recorded as a
sequence of events, providing a complete audit trail and enabling features like
event replay and temporal queries.

Current Implementations:

- Memory - Default in-memory event store (no external dependencies)
- [Message DB](./eventstore/message-db.md): PostgreSQL-based production event store

---

!!!tip "Build your own"
    All adapter types support third-party extensions via Python entry points.
    See [Building Adapters](./building-adapters.md) for an overview, or read
    [Custom Database Adapters](./database/custom-databases.md) or [Custom
    Brokers](./broker/custom-brokers.md) for detailed guides.
