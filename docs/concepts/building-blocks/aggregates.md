# Aggregates

## Why Aggregates?

In most systems, domain objects don't exist in isolation — an `Order` has
`LineItems`, a `Customer` has `Addresses`, a `Project` has `Tasks`. Without
clear boundaries, any piece of code can reach in and modify any related
object, leading to inconsistent state, broken invariants, and tangled
dependencies. When two concurrent requests modify the same cluster of
objects, there's no natural place to detect the conflict.

Aggregates solve this by drawing an explicit boundary around a cluster of
related objects. All changes within that boundary go through a single root
entity — the **aggregate root** — which enforces business rules, guards
consistency, and acts as the unit of persistence and concurrency control.
Outside code never reaches past the root to modify internal objects directly.

An aggregate is a cluster of domain objects that can be treated as a single
unit for data changes. Each aggregate has a root entity, known as the
aggregate root, responsible for enforcing business rules and ensuring the
consistency of changes within the aggregate. In Protean, **aggregate** and
**aggregate root** are treated as synonymous.

## Facts

### Aggregates are black boxes. { data-toc-label="Black Boxes" }
The external world communicates with aggregates solely through their published
API. Aggregates, in turn, communicate with the external world through
[domain events](./events.md).

### Aggregates are versioned. { data-toc-label="Versioning" }
The version is a simple incrementing number. Every new aggregate instance starts
with a version of `-1`. The version is incremented to `0` when the aggregate is
first persisted, and increases by one on each subsequent save.

### Aggregates have concurrency control. { data-toc-label="Concurrency Control" }
Aggregates are persisted with optimistic concurrency. If the expected version
of the aggregate does not match the version in the database, the transaction
is aborted.

### Aggregates enclose business invariants. { data-toc-label="Invariants" }

Aggregates contain invariants that should always be satisfied. Protean enforces
an **always-valid guarantee**: invariants are checked automatically before and
after every field change, not just at persistence time. This means an aggregate
cluster can never exist in an invalid state once constraints and invariants have
been defined. See [Invariants](../foundations/invariants.md#the-always-valid-guarantee)
for the full explanation.

Invariants can be specified at the level of an aggregate's fields, the entire
aggregate cluster, individual [entities](./entities.md), or
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

### Aggregates have configurable entity limits. { data-toc-label="Limits" }

The object graph under an aggregate is loaded eagerly. By default, queries
return up to **100** associated entities per collection (configurable via
the `limit` option on the aggregate or entity decorator). If you expect
a collection to routinely exceed this limit, rethink your aggregate boundary
— one approach is to split the aggregate into multiple aggregates, or to
promote the underlying entity to an aggregate by itself. You can also set
`limit=None` to remove the cap entirely.

---

## Next steps

For practical details on defining and using aggregates in Protean, see the guide:

- [Aggregates](../../guides/domain-definition/aggregates.md) — Defining aggregates, fields, initialization, configuration options, and associations.

Not sure whether your concept should be an aggregate, entity, or value object?

- [Choosing Element Types](./choosing-element-types.md) — Decision guide with checklists and flowcharts.

For design guidance:

- [Design Small Aggregates](../../patterns/design-small-aggregates.md) — Why smaller aggregates lead to better systems.
- [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md) — Protecting aggregate internals with controlled mutation.
- [Factory Methods for Aggregate Creation](../../patterns/factory-methods-for-aggregate-creation.md) — Encapsulating complex construction logic.
- [Model Aggregate Lifecycle as a State Machine](../../patterns/aggregate-state-machines.md) — Explicit states and guarded transitions.
- [Organize by Domain Concept](../../patterns/organize-by-domain-concept.md) — Structuring code around domain concepts rather than technical layers.
- [One Aggregate Per Transaction](../../patterns/one-aggregate-per-transaction.md) — Keeping transaction boundaries clean.
