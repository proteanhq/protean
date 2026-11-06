# Declaring Indexes

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

When an aggregate or entity is queried by anything other than its identifier,
the persistence layer needs an index to keep that query fast. Protean lets you
declare those indexes in the domain layer, next to the aggregate, with the
`indexes=` option. The framework creates them on every database adapter that
can support them.

You declare each index as an `Index` object in the `indexes=` option. For the
full `Index` option reference, see
[Indexes](../../reference/domain-elements/indexes.md). For guidance on *which*
indexes to add, see [Index Aggregates for Query
Paths](../../patterns/index-aggregates-for-query-paths.md).

---

## Declare an index on an aggregate

Pass a list of `Index` objects to the decorator. Each `Index` names the fields
it covers:

```python
--8<-- "guides/domain-definition/indexes/001.py:aggregate"
```

`Index("email", unique=True)` enforces uniqueness. `Index("status")` is a plain
lookup index. For most aggregates, these two forms are all you need.

---

## Composite and descending indexes

List several fields to build a composite index. The order matters. It should
match how you filter and sort. Use `desc=` for the fields that are read in
descending order:

```python
--8<-- "guides/domain-definition/indexes/002.py:aggregate"
```

This index supports a query that filters on `status` and returns the highest
`priority` first. The database uses the one index for both the filter and the
sort.

---

## Partial indexes

A partial index covers only the rows matching a predicate. When the rows you
query are a small slice of the table, this keeps the index tiny. Pass a
[`Q`](../change-state/retrieve-aggregates.md) predicate as `where=`:

```python
--8<-- "guides/domain-definition/indexes/003.py:aggregate"
```

Only `pending` and `failed` rows are indexed, not the (usually far larger)
completed archive. Partial indexes are honored on PostgreSQL and SQLite. On
other backends, Protean drops the predicate with a warning and creates a full
index instead, so your declaration stays portable.

---

## Covering indexes

`include=` adds non-key columns to the index so a query can be answered from
the index alone, without reading the row:

```python
--8<-- "guides/domain-definition/indexes/004.py:aggregate"
```

Covering columns are honored on PostgreSQL and SQL Server. On other backends,
Protean drops them with a warning.

---

## Indexes on entities

Entities accept the same `indexes=` option as aggregates:

```python
--8<-- "guides/domain-definition/indexes/005.py:entity"
```

---

## Indexes on projections

Projections are read-optimized query models, so they are often the most
important place to declare indexes. They accept the same `indexes=` option:

```python
--8<-- "guides/domain-definition/indexes/006.py:projection"
```

Database-backed projections get the indexes at table creation. Cache-backed
projections (for example a Redis-backed projection) silently ignore them.

## Reuse index declarations

`Index` is a plain object, so you can define indexes once and reference them.
This is useful for a shared convention or to keep a long decorator readable:

```python
--8<-- "guides/domain-definition/indexes/007.py:aggregate"
```

---

## Dialect-specific indexes

For an index the portable API cannot express (a GIN index on a JSON column, an
expression index, a dialect-only option), write raw DDL with `Index.from_sql`.
It is emitted only when the configured dialect matches:

```python
--8<-- "guides/domain-definition/indexes/008.py:aggregate"
```

Keep portable indexes (uniqueness, composite ordering) as `Index(...)` on the
aggregate. Use `Index.from_sql` for storage-specific tuning that `Index(...)`
cannot express.

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

The memory provider does not render DDL, but it does enforce declared unique
indexes (`Index(..., unique=True)`). On the memory provider, a duplicate insert
or update against a single-column or composite unique index raises
`ValidationError`, the same error Protean raises for a field-level
`unique=True`. (A SQL backend rejects the same duplicate at the database
instead.) NULLs are treated as distinct, following PostgreSQL/SQLite semantics.
Non-unique indexes remain inert on the memory provider, so you can develop
against it and move to a SQL backend without changing the domain.

!!! note "Validation"

    Index declarations are checked when the domain initializes. `Domain.init()`
    raises an error when an index references a field that does not exist, or a
    `desc`/`include` field outside the index. You see the mistake at startup
    instead of at query time.

---

## See also

- [Indexes reference](../../reference/domain-elements/indexes.md): Every `Index` option.
- [Index Aggregates for Query Paths](../../patterns/index-aggregates-for-query-paths.md): Choosing what to index.
- [Retrieve Aggregates](../change-state/retrieve-aggregates.md): The queries indexes accelerate.
