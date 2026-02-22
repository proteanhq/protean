# Repositories

A repository provides a collection-oriented interface to persist and retrieve
[aggregates](./aggregates.md). It hides the details of the underlying storage
technology behind a clean, domain-focused API — so the domain model never
knows whether its data lives in a relational database, a document store, or
an in-memory map.

Repositories are the sole gateway for aggregate persistence. If you need to
save or load an aggregate, you go through its repository.

## Facts

### Repositories have a collection-oriented design. { data-toc-label="Collection-oriented" }

A repository mimics a `set` collection. You `add` an aggregate to persist it
and `get` an aggregate to retrieve it. This design keeps the persistence
interface familiar and intentional — you work with aggregates as if they were
items in a collection, without thinking about SQL statements or storage
engines.

### Every aggregate has a repository. { data-toc-label="Default Repository" }

Protean automatically provides a default repository for every registered
aggregate. You do not need to write a repository class unless you want to add
custom query methods or override default behavior. The default repository
covers `add`, `get`, and basic retrieval out of the box.

### Custom repositories add domain-specific queries. { data-toc-label="Custom Queries" }

When you need to express business-oriented queries — such as retrieving all
overdue orders or finding customers by region — you define a custom repository
with methods whose names reflect the domain language. This keeps query logic
close to the aggregate it belongs to and makes intent explicit.

### Repositories are always associated with an aggregate. { data-toc-label="Linked to Aggregate" }

A repository is always bound to exactly one aggregate. This one-to-one
relationship ensures that each aggregate cluster has a single, well-defined
persistence entry point.

### Repositories return fully-hydrated aggregates. { data-toc-label="Eager Loading" }

When you retrieve an aggregate through its repository, the entire object
graph — including enclosed [entities](./entities.md) and
[value objects](./value-objects.md) — is loaded eagerly. You always get a
complete, consistent snapshot of the aggregate and its children.

### Repositories operate within Unit of Work transactions. { data-toc-label="Transactions" }

Every repository operation participates in the enclosing Unit of Work. This
means that adding or updating an aggregate, raising
[domain events](./events.md), and any other side effects are all committed
atomically — or rolled back together if something fails.

### Repositories abstract away storage technology. { data-toc-label="Technology-agnostic" }

The repository interface is the same regardless of which database adapter is
configured. Switching from PostgreSQL to Elasticsearch, or from a relational
store to an in-memory adapter during testing, requires no changes to domain
code.

### Repositories are the only path to persistence. { data-toc-label="Single Gateway" }

Domain objects should never interact with the database directly. All reads and
writes go through the repository, which ensures that invariants are enforced,
events are collected, and the Unit of Work can track changes.

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

Avoid exposing database-specific details — column names, join strategies, raw
query syntax — through the repository interface. The domain model should be
able to evolve independently of the storage layer.

---

## Next steps

For practical details on defining and using repositories in Protean, see the
guide pages:

- [Repositories](../../guides/change-state/repositories.md) — Defining
  custom repositories, the DAO layer, and database-specific repositories.
- [Retrieving Aggregates](../../guides/change-state/retrieve-aggregates.md) —
  QuerySets, filtering, Q objects, bulk operations, and result navigation.
