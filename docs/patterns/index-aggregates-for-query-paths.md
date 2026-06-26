# Index Aggregates for Query Paths

## The Problem

An aggregate is loaded by its identifier on the write path, and the database
gives you that lookup for free through the primary key. But the read path rarely
queries by identifier. A worker polls for the next *pending* job ordered by
*priority*. A projection rebuild scans by *correlation id*. A dashboard filters
by *status* and *created date*. None of those are primary-key lookups.

Without an index, the database answers each of those queries with a full table
scan. It works in development, where the table holds a few hundred rows, and
quietly degrades in production as the table grows. The failure mode is
insidious: nothing errors, queries just get slower, and the cause is invisible
in the domain code. The team discovers the missing index by watching the
database burn.

The framework already knows which queries it issues. The outbox poll, the
process-manager correlation lookup, the uniqueness check on an identifier —
these are structural, not incidental. The query shape is knowable when the
aggregate is designed, not just when it is profiled.

## The Pattern

Declare the indexes an aggregate needs *as part of the aggregate*, in the domain
layer, alongside the fields and invariants. An index that backs a query path or
encodes a uniqueness invariant is a property of the model, not an afterthought
for an operator to discover.

Three forces shape what to declare:

### 1. Index the query path, not every field

Add an index for each non-primary-key access path the aggregate actually has:
a uniqueness constraint on a natural identifier, a composite index whose column
order matches a filter-plus-sort, a single-column index for a correlation
lookup. Do not index fields nothing queries — every index costs write
throughput and storage.

### 2. Match composite order to filter-then-sort

A composite index serves a query when its leading columns match the filter and
its trailing columns match the sort. `(status, priority DESC)` backs "the
pending jobs, highest priority first" with one index. The order is part of the
design, not a detail.

### 3. Keep the working set small with partial indexes

When the rows you query are a small slice of the table — the *active* rows
against a large archive of *completed* ones — a partial index covers only that
slice. The index stays proportional to the working set, not the table, which is
often a 100×+ difference.

## How Protean Supports It

Indexes are declared with the `indexes=` decorator option, using portable
`Index` objects:

```python
from protean import Index, Q


@domain.aggregate(indexes=[
    Index("status", "priority", desc=("priority",),
          where=Q(status__in=["pending", "failed"]), name="ix_active"),
    Index("message_id", unique=True),
    Index("correlation_id"),
])
class Outbox:
    ...
```

The portable subset (composite, descending, unique, naming) is honored by every
SQL adapter. Opt-in features degrade gracefully: a partial `where=` or covering
`include=` that a dialect cannot support falls back to a full index with a
logged warning, so the same declaration is correct on PostgreSQL, SQLite, and
SQL Server. Storage-specific indexes (GIN, BRIN, expression indexes) drop to
`Index.from_sql(dialect, ddl)`, keeping the aggregate clean while still
expressing the tuning.

This is exactly how Protean's own `Outbox` is indexed — the example above ships
with the framework. See the [Indexes reference](../reference/domain-elements/indexes.md)
for the full option set and [ADR-0014](../adr/0014-aggregate-metadata-decorator-params-over-meta-class.md)
for why indexes live on the decorator.

## Applying the Pattern

Start from the queries, not the fields. For each aggregate, list the access
paths beyond primary-key load:

- **A uniqueness invariant** (`email`, an external reference, a `message_id`):
  a `unique=True` index both enforces the rule and accelerates the lookup.
- **A filter-plus-sort hot path** (the polling query): a composite index with
  `desc=` on the sort column.
- **A correlation or foreign lookup** (process managers, cross-aggregate
  references): a single-column index.
- **A hot subset of a large table** (active vs. archived): add `where=` to make
  it partial.

```python
@domain.aggregate(indexes=[
    Index("email", unique=True),                       # uniqueness invariant
    Index("organization_id"),                          # foreign lookup
    Index("status", "created_at", desc=("created_at",), # filter + sort
          where=Q(status="open"), name="ix_open"),     # hot subset
])
class Ticket:
    ...
```

Then render and review the DDL before it reaches a database:

```bash
protean schema render --indexes --domain=my_app.domain
```

## Anti-Patterns

### Indexing every field "just in case"

Each index slows every write and consumes storage. An index that no query uses
is pure cost. Index the access paths you have, and add new indexes when new
query paths appear — not preemptively.

### Leaving indexes to the operator

Defining the aggregate in the domain and the indexes in a hand-maintained
migration splits one decision across two places that drift apart. The aggregate
author knows the query shape; capture it where the aggregate is defined.

### A composite index in the wrong order

`(priority, status)` does not serve "filter by status, sort by priority" —
the leading column must match the filter. Column order is not cosmetic; an
index in the wrong order is an index the query cannot use.

### Smuggling storage tuning into the domain

A GIN index on a JSON blob is storage-specific and only meaningful on
PostgreSQL. Putting dialect-only DDL inline pollutes the portable declaration.
Use `Index.from_sql` (and prefer the model decorator) for tuning that only one
backend understands.

## When Not to Use / Trade-offs

- **Small, bounded tables** (reference data, configuration) rarely need indexes
  beyond the primary key; a scan over a few hundred rows is cheap.
- **Write-heavy, read-rare aggregates** pay the index write cost on every
  insert for a query that almost never runs. Weigh the read benefit against the
  write tax.
- **The memory provider** ignores indexes (they are advisory there), so the
  benefit only materializes on a real SQL backend. This is intentional — it
  keeps development against memory friction-free — but means index quality is
  not exercised until you run against PostgreSQL or SQLite.
- **Event-sourced aggregates** are reconstructed from their event stream, not
  queried as tables, so table indexes on them do not apply.

## Summary

| Question | Answer |
|----------|--------|
| What do I index? | The non-primary-key query paths the aggregate actually has. |
| Where do I declare it? | On the aggregate, via `@domain.aggregate(indexes=[...])`. |
| How do I back a filter + sort? | A composite `Index` with `desc=` matching the sort. |
| How do I keep a hot-set index small? | A partial index with `where=Q(...)`. |
| What about GIN/BRIN/expression indexes? | `Index.from_sql(dialect, ddl)`. |
| How do I apply them? | `protean db setup`, or render with `protean schema render --indexes`. |

---

## Related reading

- [Declaring Indexes](../guides/domain-definition/indexes.md): the how-to guide.
- [Indexes reference](../reference/domain-elements/indexes.md): every `Index` option and dialect support.
- [Design Small Aggregates](design-small-aggregates.md): smaller aggregates have simpler, cheaper indexes.
