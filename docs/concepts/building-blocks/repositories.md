# Repositories

A repository provides a collection-oriented interface to persist and retrieve
[aggregates](./aggregates.md). A repository exposes a clean, domain-focused API
and keeps the details of the storage technology inside it. The domain model
never knows whether its data is stored in a relational database, a document
store, or an in-memory map.

Repositories are the only way to persist aggregates. If you need to save or
load an aggregate, you go through its repository.

## Facts

### Repositories have a collection-oriented design. { data-toc-label="Collection-oriented" }

A repository mimics a `set` collection. You `add` an aggregate to persist it
and `get` an aggregate to retrieve it. This design keeps the persistence
interface familiar and intentional. You work with aggregates as if they were
items in a collection, without thinking about SQL statements or storage
engines.

### Every aggregate has a repository. { data-toc-label="Default Repository" }

Protean automatically provides a default repository for every registered
aggregate. You do not need to write a repository class unless you want to add
custom query methods or override default behavior. The default repository
covers `add`, `get`, and basic retrieval.

### Custom repositories add domain-specific queries. { data-toc-label="Custom Queries" }

When you need to express business-oriented queries (such as retrieving all
overdue orders or finding customers by region) you define a custom repository
with methods whose names reflect the domain language. This keeps query logic
close to the aggregate it belongs to and makes intent explicit.

### Repositories are always associated with an aggregate. { data-toc-label="Linked to Aggregate" }

A repository is always bound to exactly one aggregate. Because of this
one-to-one binding, each aggregate cluster has a single, well-defined
persistence entry point.

### Repositories return fully-hydrated aggregates. { data-toc-label="Eager Loading" }

When you retrieve an aggregate through its repository, the entire object graph,
including enclosed [entities](./entities.md) and [value
objects](./value-objects.md), is loaded eagerly. You always get a complete,
consistent snapshot of the aggregate and its children.

### Repositories operate within Unit of Work transactions. { data-toc-label="Transactions" }

Every repository operation participates in the enclosing Unit of Work. The Unit
of Work commits added or updated aggregates, raised
[domain events](./events.md), and any other side effects atomically. If
something fails, it rolls them all back together.

### Repositories abstract away storage technology. { data-toc-label="Technology-agnostic" }

The repository interface is the same regardless of which database adapter is
configured. Switching from PostgreSQL to Elasticsearch, or from a relational
store to an in-memory adapter during testing, requires no changes to domain
code.

### Repositories are the only path to persistence. { data-toc-label="Single Gateway" }

Domain objects should never interact with the database directly. All reads and
writes go through the repository, which ensures that invariants are enforced,
events are collected, and the Unit of Work can track changes.

### Repositories do not support hard deletion. { data-toc-label="No Delete" }

Repositories intentionally have no `delete` or `remove` method. Domain state
changes (cancellation, deactivation, archival) should be modeled as explicit
state transitions through commands and events, not as record erasure. Hard
deletion is available at the infrastructure level (`_dao.delete()`) for
scenarios like projection rebuilds, test teardown, and compliance requirements.

### Event-sourced aggregates get a different repository. { data-toc-label="Event Sourced" }

When an aggregate is configured with `event_sourced=True`,
`domain.repository_for()` transparently returns an event-sourced repository.
The event-sourced repository reconstructs state by replaying events from the
aggregate's stream instead of reading from a database table. The calling code
does not change.

## Best Practices

### Name query methods after domain concepts. { data-toc-label="Domain Naming" }

A method named `for_region(region)` is more expressive than a generic
`filter(region=region)`. When your repository speaks the ubiquitous language,
the code becomes self-documenting.

### Keep repositories thin. { data-toc-label="Thin Repositories" }

Repositories should contain query logic, not business logic. If a retrieval
method starts making decisions or enforcing rules, that logic belongs in the
aggregate or a [domain service](./domain-services.md).

### Do not leak persistence concerns. { data-toc-label="No Leaking" }

Avoid exposing database-specific details (column names, join strategies, raw
query syntax) through the repository interface. The domain model should be able
to evolve independently of the storage layer.

---

## Next steps

For practical details on defining and using repositories in Protean, see the
guide pages:

- [Repositories](../../guides/change-state/repositories.md): Defining
  custom repositories, the DAO layer, and database-specific repositories.
- [Retrieving Aggregates](../../guides/change-state/retrieve-aggregates.md):
  QuerySets, filtering, Q objects, bulk operations, and result navigation.
