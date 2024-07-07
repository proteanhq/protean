# Adapters

A core tenet in Protean's philosophy is to separate the domain
from the underlying infrastructure. It enables you to code
and test models without worrying about technology and plug in a
component when ready. This lets you delay your decision on technology
until [the last responsible moment](https://blog.codinghorror.com/the-last-responsible-moment/).

Protean's design is based on the [Ports and Adapters architecture](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)),
also known as Hexagonal Architecture,
allowing loosely coupled components that can be easily connected and swapped.

**Ports** are abstract interfaces that define a specific type of interaction
between the application and the outside world. They define a protocol that can
be implemented by concrete technology implementations called adapters. 

**Adapters** are the glue between the application and the outside world. They
tailor the exchanges between the external technology and the ports that
represent the requirements of the inside of the application.

Protean exposes several ports with an array of built-in adapters for
each port.

## Database

The [Database port](./database/index.md) defines the interface for interacting
with persistent storage
systems. It abstracts the underlying database technology, allowing Protean to
support various databases without changing the core application logic.

Current Implementations:

- [PostgreSQL](./database/postgresql.md)
- [Elasticsearch](./database/elasticsearch.md)
- [Redis](./database/redis.md)

## Broker

The [Broker port](./broker/index.md) defines the interface for message brokers and pub/sub systems.
It enables communication between different parts of the ecosystem via messages,
facilitating asynchronous processing and decoupling.

!!!note
    Protean internally uses an Event Store that acts both as an event
    storage mechanism as well as a message delivery mechanism within a Protean-based
    application. Brokers are more focused on integration with other systems.

Current Implementations:

- [Redis](./broker/redis.md)

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
    [contributing adapters](../community/contributing/adapters.md) for more
    information.
    
    You can sponsor an adapter if you want to fast-track its implemetation.
    [Get in touch](mailto:sponsor@ambitious.systems) with us for a discussion.
