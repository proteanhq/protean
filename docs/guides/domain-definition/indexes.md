# Declaring Indexes

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

When an aggregate or entity is queried by anything other than its identifier,
the persistence layer needs an index to keep that query fast. Protean lets you
declare those indexes in the domain layer, next to the aggregate, with the
`indexes=` option. The framework creates them on every database adapter that
can support them.

This guide shows how to declare indexes. For the full `Index` option reference
see [Indexes](../../reference/domain-elements/indexes.md); for guidance on
*which* indexes to add, see
[Index Aggregates for Query Paths](../../patterns/index-aggregates-for-query-paths.md).

---

## Declare an index on an aggregate

Pass a list of `Index` objects to the decorator. Each `Index` names the fields
it covers:

```python
from protean import Index


@domain.aggregate(indexes=[
    Index("email", unique=True),
    Index("status"),
])
class Customer:
    email = String(max_length=255, required=True)
    status = String(max_length=32, default="active")
```

`Index("email", unique=True)` enforces uniqueness; `Index("status")` is a
plain lookup index. That is the whole surface for the common case.

---

## Composite and descending indexes

List several fields to build a composite index. The order matters — it should
match how you filter and sort. Use `desc=` for the fields that are read in
descending order:

```python
@domain.aggregate(indexes=[
    Index("status", "priority", desc=("priority",)),
])
class Job:
    status = String(max_length=32)
    priority = Integer(default=0)
```

This backs a query that filters on `status` and returns the highest
`priority` first — a single index serves both the filter and the sort.

---

## Partial indexes

A partial index covers only the rows matching a predicate. When the rows you
query are a small slice of the table, this keeps the index tiny. Pass a
[`Q`](../change-state/retrieve-aggregates.md) predicate as `where=`:

```python
from protean import Index, Q


@domain.aggregate(indexes=[
    Index("status", where=Q(status__in=["pending", "failed"]), name="ix_active"),
])
class Task:
    status = String(max_length=32)
```

Only `pending` and `failed` rows are indexed, not the (usually far larger)
completed archive. Partial indexes are honored on PostgreSQL and SQLite; on
other backends the predicate is dropped (with a warning) and a full index is
created instead, so your declaration stays portable.

---

## Covering indexes

`include=` adds non-key columns to the index so a query can be answered from
the index alone, without reading the row:

```python
@domain.aggregate(indexes=[
    Index("status", include=("priority",), name="ix_status_cover"),
])
class Job:
    status = String(max_length=32)
    priority = Integer()
```

Covering columns are honored on PostgreSQL and SQL Server; elsewhere they are
dropped (with a warning).

---

## Indexes on entities

Entities accept the same `indexes=` option as aggregates:

```python
@domain.entity(part_of=Order, indexes=[Index("sku", unique=True)])
class LineItem:
    sku = String(max_length=64)
    quantity = Integer()
```

---

## Indexes on projections

Projections are read-optimized query models, so they are often the most
important place to declare indexes. They accept the same `indexes=` option:

```python
@domain.projection(indexes=[Index("status"), Index("customer_id")])
class OrderSummary:
    id = Identifier(identifier=True)
    status = String(max_length=32)
    customer_id = String(max_length=64)
```

Database-backed projections get the indexes at table creation. Cache-backed
projections (for example a Redis-backed projection) silently ignore them.

## Reuse index declarations

`Index` is a plain object, so you can define indexes once and reference them —
handy for a shared convention or to keep a long decorator readable:

```python
ACTIVE_TASKS = Index(
    "status", "priority",
    desc=("priority",),
    where=Q(status__in=["pending", "failed"]),
    name="ix_active",
)


@domain.aggregate(indexes=[ACTIVE_TASKS, Index("correlation_id")])
class Task:
    ...
```

---

## Dialect-specific indexes

For an index the portable API cannot express (a GIN index on a JSON column, an
expression index, a dialect-only option), drop down to raw DDL with
`Index.from_sql`. It is emitted only when the configured dialect matches:

```python
@domain.aggregate(indexes=[
    Index.from_sql(
        "postgresql",
        "CREATE INDEX ix_doc_data_gin ON document USING gin (data jsonb_path_ops)",
    ),
])
class Document:
    data = Dict()
```

Keep portable indexes (uniqueness, composite ordering) as `Index(...)` on the
aggregate; reach for `Index.from_sql` only for storage-specific tuning.

---

## Create the indexes

On SQLAlchemy providers, declared indexes are created together with the table:

```bash
protean db setup
```

To review the DDL first, or to apply it through your own migration tooling,
render per-dialect `.sql` files instead of executing anything:

```bash
protean schema render --indexes --domain=my_app.domain
```

This writes `<schema_name>.indexes.<dialect>.sql` files under
`.protean/schemas/`. See
[`protean schema render`](../../reference/cli/schema.md#protean-schema-render).

The memory provider accepts index declarations but does not enforce them, so
you can develop against it and move to a SQL backend without changing the
domain.

!!! note "Validation"

    Index declarations are checked when the domain initializes. Referencing a
    field that does not exist (or a `desc`/`include` field that is not part of
    the index) raises an error at `Domain.init()`, so mistakes surface at
    startup rather than at query time.

---

## See also

- [Indexes reference](../../reference/domain-elements/indexes.md) — every `Index` option.
- [Index Aggregates for Query Paths](../../patterns/index-aggregates-for-query-paths.md) — choosing what to index.
- [Retrieve Aggregates](../change-state/retrieve-aggregates.md) — the queries indexes accelerate.
