# Projections

A projection is a read-optimized, denormalized view of domain data. It
exists on the query side of a CQRS architecture, purpose-built to serve
specific read use-cases efficiently — without the constraints or complexity
of the domain model that produced the data.

Projections are populated by [projectors](./projectors.md) in response to
[domain events](./events.md). They are never written to directly by domain
logic.

## Facts

### Projections are query-optimized data structures. { data-toc-label="Query-optimized" }

A projection is shaped for the needs of the reader, not the writer.
It may flatten nested relationships, pre-compute derived values, or combine
data from multiple [aggregates](./aggregates.md) into a single queryable
record. The goal is to make reads fast, simple, and free from joins or
post-processing.

### Projections only support simple field types. { data-toc-label="Simple Fields" }

Unlike aggregates and entities, projections cannot contain associations,
references, or nested [value objects](./value-objects.md). They hold only
simple, scalar field types — strings, integers, floats, identifiers,
timestamps. This restriction keeps projections close to the storage layer and
avoids the complexity of object-graph management on the read side.

### Projections can be stored in a database or cache. { data-toc-label="Storage Options" }

A projection can be persisted to a database provider for durable storage, or
to a cache (such as Redis) for high-speed access. The choice depends on the
read pattern — caching suits high-throughput, low-latency lookups, while
database storage suits complex queries and long-term retention.

### Every projection has at least one identifier. { data-toc-label="Identity" }

Each projection must define at least one identifier field. This ensures every
projection record can be uniquely addressed for retrieval, updating, and
deletion.

### Projections are populated by projectors. { data-toc-label="Populated by Projectors" }

Projections do not decide how they are built — that responsibility belongs to
[projectors](./projectors.md). Projectors listen to domain events and write
or update projection records accordingly. The projection itself is a passive
data structure.

### Projections enable read/write separation. { data-toc-label="CQRS Read Side" }

By decoupling the read model from the write model, projections allow each side
to evolve independently. The write side can be normalized and optimized for
business-rule enforcement, while the read side can be denormalized and
optimized for query performance. Changes to one do not force changes on the
other.

### Projections can aggregate data across aggregates. { data-toc-label="Cross-Aggregate Views" }

A single projection can combine data from multiple aggregate streams. For
example, an "Order Summary" projection might incorporate data from Order,
Customer, and Inventory aggregates — something that would be impractical to
query against the write-side models.

### Projection schemas are independent of aggregate schemas. { data-toc-label="Independent Schema" }

A projection's field structure does not need to mirror the aggregate that
produced the data. Fields can be renamed, combined, filtered, or derived to
suit the specific query use-case the projection serves.

---

## Next steps

For practical details on defining and using projections in Protean, see the guide:

- [Projections](../../guides/consume-state/projections.md) — Defining projections, configuration options, querying, projector setup, and testing.

For design guidance:

- [Design Events for Consumers](../../patterns/design-events-for-consumers.md) — Structuring events so projectors can build reliable read models.
