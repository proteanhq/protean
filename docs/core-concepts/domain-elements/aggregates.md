# Aggregates

An aggregate is a cluster of domain objects that can be treated as a single
unit for data changes.

Each aggregate has a root entity, known as the aggregate root,
responsible for enforcing business rules and ensuring the consistency of
changes within the aggregate. In Protean, **aggregate** and **aggregate root**
are treated as synonymous.

Aggregates help to maintain the integrity of the data by defining boundaries
within which invariants must be maintained.

## Facts

### Aggregates are black boxes. { data-toc-label="Black Boxes" }
The external world communicates with aggregates solely through their published
API. Aggregates, in turn, communicate with the external world through
[domain events](./events.md).

### Aggregates are versioned. { data-toc-label="Versioning" }
The version is a simple incrementing number. Every aggregate instance's version
starts at 0.

### Aggregates have concurrency control. { data-toc-label="Concurrency Control" }
Aggregates are persisted with optimistic concurrency. If the expected version
of the aggregate does not match the version in the database, the transaction
is aborted.

### Aggregates enclose business invariants. { data-toc-label="Invariants" }

Aggregates contain invariants that should always be satisfied - they
are checked before and after every change to the aggregate. Invariants can be
specified at the level of an aggregate's fields, the entire aggregate cluster,
individual [entities](./entities.md), or
[domain services](./domain-services.md) that operate on multiple aggregates.

## Object Graphs

Aggregates compose a graph of enclosed elements. The objects themselves can nest
other objects and so on infinitely, though it is recommended to not go beyond
2 levels.

### Aggregates can hold two types of objects - Entities and Value Objects. { data-toc-label="Types of Objects" }
[Entities](./entities.md) are objects with an identity.
[Value objects](./value-objects.md) don't have identity; their data defines
their identity.

### Entities are accessible only via aggregates. { data-toc-label="Entity Access" }
Entities within aggregates are loaded and accessible only through the aggregate.
All changes to entities should be driven through the aggregates.

## Persistence

Data persistence and retrieval are always at the level of an aggregate.
They internally load and manage the objects within their cluster.

### Aggregates persist data with the help of Repositories. { data-toc-label="Repositories" }

Aggregates are persisted and retrieved with the help of
[repositories](./repositories.md). Repositories are collection-oriented - they
mimic how a collection data type, like list, dictionary, and set, would work.
Repositories can be augmented with custom methods to perform business queries.

### Aggregates are transaction boundaries.  { data-toc-label="Transactions" }

All changes to aggregates are performed within a transaction. This means that
all objects in the aggregates cluster are enclosed in a single transaction
during persistence. This also means that all objects within an
aggregate cluster are kept together in the same persistence store.

### Aggregates can enclose up to 500 entities. { data-toc-label="Limits" }

The object graph under an aggregate is loaded eagerly. The number of associations
under an aggregate is limited to 500. If you expect the number of entities to
exceed this limit, rethink your aggregate boundary. One way would be to split
the aggregate into multiple aggregates. Another would be to make the underlying
entity an aggregate by itself.
