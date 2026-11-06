# Index Aggregates for Query Paths

## The Problem

On the write path, the repository loads an aggregate by its identifier. The
database serves that lookup through the primary key, with no index for you to
declare. But the read path rarely queries by identifier. A worker polls for the
next *pending* job ordered by *priority*. A projection rebuild scans by
*correlation id*. A dashboard filters by *status* and *created date*. None of
those are primary-key lookups.

Without an index, the database answers each of those queries with a full table
scan. The scan works in development, where the table holds a few hundred rows.
In production, the scan gets slower as the table grows, and nothing reports it.
This failure is hard to spot, because nothing raises an error and the queries
only get slower. The domain code shows no sign of the cause. The team finds the
missing index only after database load and query times climb.

The framework already knows which queries it issues. The outbox poll, the
process-manager correlation lookup, the uniqueness check on an identifier.
These are structural, not incidental. You can know the query shape when you
design the aggregate. You do not have to wait until you profile it.

## The Pattern

Declare the indexes an aggregate needs *as part of the aggregate*, in the
domain layer, alongside the fields and invariants. An index that backs a query
path or encodes a uniqueness invariant is a property of the model. An operator
should not have to find it later in production.

Use three rules to decide which indexes to declare:

### 1. Index the query path, not every field

Add an index for each non-primary-key access path the aggregate actually has: a
uniqueness constraint on a natural identifier, a composite index whose column
order matches a filter-plus-sort, a single-column index for a correlation
lookup. Do not index fields nothing queries. Every index costs write throughput
and storage.

### 2. Match composite order to filter-then-sort

A composite index serves a query when its leading columns match the filter and
its trailing columns match the sort. `(status, priority DESC)` backs "the
pending jobs, highest priority first" with one index. The order is part of the
design, not a detail.

### 3. Keep the working set small with partial indexes

Sometimes the rows you query are a small slice of the table, such as the
*active* rows against a large archive of *completed* ones. A partial index
covers only that slice. The index stays proportional to the working set, not
the table, which is often a 100×+ difference.

## How Protean Supports It

Indexes are declared with the `indexes=` decorator option, using portable
`Index` objects:

```python
--8<-- "patterns/index-aggregates-for-query-paths/001.py:outbox"
```

The portable subset (composite, descending, unique, naming) is honored by every
SQL adapter. When a dialect cannot support an opt-in feature, such as a partial
`where=` or a covering `include=`, Protean falls back to a full index and logs
a warning. The same declaration is therefore correct on PostgreSQL, SQLite, and
SQL Server. For storage-specific indexes (GIN, BRIN, expression indexes), use
`Index.from_sql(dialect, ddl)`. It expresses the tuning without adding
dialect-only options to the aggregate's portable declarations.

Protean's own `Outbox` is indexed almost the same way, with three differences.
Its partial polling index is named `ix_outbox_active` and covers `status`,
`priority`, `created_at` and `sequence_number`. The two extra columns match the
order the framework claims rows in: higher priority first, then commit order.
Its unique index covers `message_id` and `target_broker` together, because the
framework writes one outbox row per target broker for each message. It also has
`ix_outbox_hold_back` on `target_broker`, `stream_category`, `partition_key`
and `status`, which the claim uses to find a partition key's earlier rows. The
`correlation_id` index is the same as in the example above. See the [Indexes
reference](../reference/domain-elements/indexes.md) for the full option set.
See
[ADR-0014](../adr/0014-aggregate-metadata-decorator-params-over-meta-class.md)
for why you declare indexes on the decorator.

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
--8<-- "patterns/index-aggregates-for-query-paths/002.py:ticket"
```

Then render the DDL for review before you apply it to a database:

```bash
protean schema render --indexes --domain=my_app.domain
```

## Anti-Patterns

### Indexing every field "just in case"

Each index slows every write and consumes storage. An index that no query uses
is pure cost. Index the access paths you have, and add new indexes when new
query paths appear, not preemptively.

### Leaving indexes to the operator

When you define the aggregate in the domain and its indexes in a
hand-maintained migration, you split one decision across two places. Over time,
one place changes and the other does not. The aggregate author knows the query
shape; capture it where the aggregate is defined.

### Putting composite index columns in the wrong order

`(priority, status)` does not serve "filter by status, sort by priority". The
leading column must match the filter. Column order is not cosmetic; an index in
the wrong order is an index the query cannot use.

### Putting storage-specific tuning in the domain declaration

A GIN index on a JSON blob is storage-specific and only meaningful on
PostgreSQL. Inline dialect-only DDL adds options that only one database
understands to the portable declaration. Use `Index.from_sql` (and prefer the
model decorator) for tuning that only one backend understands.

## When Not to Use / Trade-offs

- **Small, bounded tables** (reference data, configuration) rarely need indexes
  beyond the primary key; a scan over a few hundred rows is cheap.
- **Write-heavy, read-rare aggregates** pay the index write cost on every
  insert for a query that almost never runs. Weigh the read benefit against the
  extra cost on every write.
- **The memory provider** ignores indexes (they are advisory there), so the
  benefit only materializes on a real SQL backend. The memory provider ignores
  indexes on purpose, so that development against memory needs no index setup.
  As a result, you do not exercise index quality until you run against
  PostgreSQL or SQLite.
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

## See also

- [Declaring Indexes](../guides/domain-definition/indexes.md): The how-to guide.
- [Indexes reference](../reference/domain-elements/indexes.md): Every `Index` option and dialect support.
- [Design Small Aggregates](design-small-aggregates.md): Smaller aggregates have simpler, cheaper indexes.
