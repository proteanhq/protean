# Indexes

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

`Index` declarations tell the persistence layer which indexes to create for an
aggregate, entity, or projection. They are passed as the `indexes=` option on
the `@domain.aggregate` / `@domain.entity` / `@domain.projection` decorators and
are honored by every database adapter that can support them. (Projections, as
read-optimized query models, are an especially natural place to declare
indexes.)

```python
from protean import Index, Q


@domain.aggregate(indexes=[
    Index("status", "priority", desc=("priority",)),
    Index("email", unique=True),
    Index("status", where=Q(status__in=["pending", "failed"]), name="ix_active"),
])
class Order:
    ...
```

For the design rationale (why indexes are decorator parameters rather than a
`class Meta:` block, and the split between portable indexes on the aggregate and
storage-specific tuning on the model) see
[ADR-0014](../../adr/0014-aggregate-metadata-decorator-params-over-meta-class.md).

---

## `Index`

```python
Index(*fields, name=None, unique=False, desc=(), where=None, include=())
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `*fields` | `str` | — | **Required.** One or more field names, in index order. At least one. |
| `name` | `str \| None` | `None` | Explicit index name. Derived deterministically when omitted (see [Naming](#naming)). |
| `unique` | `bool` | `False` | Enforce uniqueness across the indexed fields. |
| `desc` | `tuple[str, ...]` | `()` | Subset of `fields` to index in descending order. Every entry must also appear in `fields`. |
| `where` | [`Q`](../../concepts/internals/query-system.md) `\| None` | `None` | Partial-index predicate. Honored on PostgreSQL and SQLite; ignored with a warning elsewhere. |
| `include` | `tuple[str, ...]` | `()` | Covering (non-key) columns. Honored on PostgreSQL and SQL Server; ignored with a warning elsewhere. |

`Index` is a frozen value object. Field names are validated against the
element's declared fields during `Domain.init()`.

### Naming

When `name` is omitted, the index name is derived as
`<prefix>_<table>_<fields>`, where the prefix is `uq` for unique indexes and
`ix` otherwise:

| Declaration | Derived name (table `order`) |
|-------------|------------------------------|
| `Index("status", "priority")` | `ix_order_status_priority` |
| `Index("email", unique=True)` | `uq_order_email` |

Provide an explicit `name=` when you need a stable, well-known identifier (for
example to reference it from a migration or a monitoring query).

---

## `Index.from_sql`

```python
Index.from_sql(dialect, ddl, name=None) -> RawIndex
```

An escape hatch for dialect-specific DDL the portable `Index` API cannot model
(GIN/GiST/BRIN, expression indexes, dialect-only options). The schema generator
and the SQLAlchemy adapter emit the verbatim `ddl` **only** when the configured
dialect matches `dialect`.

```python
@domain.aggregate(indexes=[
    Index.from_sql(
        "postgresql",
        "CREATE INDEX ix_order_data_gin ON order USING gin (data jsonb_path_ops)",
    ),
])
class Order:
    ...
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `dialect` | `str` | Dialect the DDL targets (`"postgresql"`, `"sqlite"`, `"mssql"`). |
| `ddl` | `str` | Verbatim `CREATE INDEX …` statement. |
| `name` | `str \| None` | Optional name, for reporting. |

`RawIndex` is the return type of `from_sql`. You never construct it directly —
always go through `Index.from_sql`.

---

## Dialect support

The portable subset (composite, descending, unique, naming) is honored
everywhere indexes apply. The opt-in features (`where`, `include`) are honored
only where the dialect supports them, and otherwise degrade to a full index
with a logged warning — declarations never fail because of an unsupported
opt-in.

| Feature | PostgreSQL | SQLite | SQL Server | Memory | Elasticsearch |
|---------|:----------:|:------:|:----------:|:------:|:-------------:|
| Composite, `unique`, `desc`, naming | ✅ | ✅ | ✅ | advisory | — |
| `where` (partial index) | ✅ | ✅ | ⚠️ falls back | advisory | — |
| `include` (covering columns) | ✅ | ⚠️ falls back | ✅ | advisory | — |
| `Index.from_sql` | matched dialect only | matched dialect only | matched dialect only | — | — |

- **SQLAlchemy providers (PostgreSQL, SQLite, SQL Server)** translate
  declarations into SQLAlchemy `Index` constructs at table-build time, emitted
  by `create_all()` / `protean db setup`. Unsupported `where`/`include` log a
  warning and fall back to a full index.
- **Memory** treats declarations as advisory: they are validated for shape but
  not enforced, so you can develop against the memory provider and switch to a
  SQL backend without code changes.
- **Elasticsearch** does not map relational indexes; use ES field mappings or
  `Index.from_sql` where applicable.
- **Non-SQL backends** (memory, Elasticsearch, and cache stores such as Redis
  for cache-backed projections) **silently ignore** index declarations — no
  warning is emitted. Declarations stay valid (field references are still
  checked at `Domain.init()`) and take effect if the element is later persisted
  to a SQL backend. Warnings are emitted **only** by SQL providers, and only
  for an opt-in (`where=`/`include=`) a specific dialect cannot honor.

See the per-adapter pages under
[Database Providers](../adapters/database/index.md) for specifics.

---

## Validation

Index declarations are validated during `Domain.init()` (after reference
resolution), raising `IncorrectUsageError` on:

- a field that is not declared on the element (in `fields`, `desc`, or
  `include`);
- a `desc` entry not present in `fields`;
- a list entry that is neither an `Index` nor a `RawIndex`.

`RawIndex` entries are opaque verbatim DDL and are not introspected.

---

## Generating DDL artifacts

`protean schema render --indexes` renders declared indexes to per-dialect
`.sql` files without touching a database. See
[`protean schema render`](../cli/schema.md#protean-schema-render).

---

## Related

- [Element Decorators](element-decorators.md) — the `indexes=` option in context.
- [Declaring Indexes](../../guides/domain-definition/indexes.md) — the how-to guide.
- [Index Aggregates for Query Paths](../../patterns/index-aggregates-for-query-paths.md) — when and what to index.
- [ADR-0014](../../adr/0014-aggregate-metadata-decorator-params-over-meta-class.md) — design rationale.
