# Query system

Protean's query system provides a database-agnostic way to filter, sort, and
paginate aggregates. This page explains the internal architecture -- the
layered design, how Q objects form expression trees, how lookups are resolved
by database providers, and how QuerySets achieve lazy evaluation.

For practical usage, see the
[Retrieving Aggregates](../../guides/change-state/retrieve-aggregates.md) guide.

---

## Architecture

The query system is organized as a chain of layers, each with a distinct
responsibility:

```
Application code
    │
    ▼
Repository           Domain-facing API: add(), get(), custom methods
    │
    ▼
DAO (BaseDAO)        Database-facing API: filter, create, update, delete
    │
    ▼
QuerySet             Lazy query builder: chains filter/exclude/limit/order_by
    │
    ▼
Provider             Database connection manager, lookup registry
    │
    ▼
Database             Actual storage (Memory, PostgreSQL, Elasticsearch, ...)
```

### Repository → DAO

Every repository has a `_dao` property that provides access to the Data
Access Object. The DAO is constructed lazily and cached:

```
BaseRepository._dao
    → provider.get_dao(entity_cls, database_model_cls)
        → ConcreteDAO(domain, provider, entity_cls, database_model_cls)
```

The repository speaks domain language (`add`, `get`, `query`, `find_by`, and
custom methods). The DAO speaks database language (`_filter`, `_count`,
`_create`, `_update`, `_delete`). Custom repository methods use `self.query`
and `self.find_by` (which delegate to the internal `_dao`) to build queries.

**Key source files:**

- `src/protean/core/repository.py` -- `BaseRepository` with `add()`, `get()`,
  `_dao` property, and `_sync_children()` for cascading child entities.
- `src/protean/port/dao.py` -- `BaseDAO` with lifecycle methods (`get`,
  `find_by`, `exists`, `create`, `save`, `update`, `delete`) and abstract
  methods for concrete implementations (`_filter`, `_count`, `_create`,
  `_update`, `_delete`, `_raw`).

### DAO → QuerySet

The DAO's `.query` property returns a fresh `QuerySet` instance. The QuerySet
is the primary query-building interface:

```python
# DAO.__init__()
self.query = QuerySet(self, domain, self.entity_cls)
```

Each QuerySet method (`filter`, `exclude`, `limit`, `offset`, `order_by`)
returns a **clone** of the QuerySet with the new criteria applied. The
original QuerySet is never mutated. This clone-on-write design enables safe
chaining:

```python
base = dao.query.filter(country="CA")       # QuerySet 1
adults = base.filter(age__gte=18)            # QuerySet 2 (clone of 1)
children = base.filter(age__lt=18)           # QuerySet 3 (clone of 1)
# base, adults, and children are all independent
```

**Key source file:** `src/protean/core/queryset.py`

### QuerySet → Provider → Database

When a QuerySet is evaluated (via `.all()`, iteration, `len()`, etc.), it
calls the DAO's `_filter` method:

```python
results = self._owner_dao._filter(
    self._criteria,     # Q object tree
    self._offset,       # int
    self._limit,        # int or None
    self._order_by      # list of strings
)
```

The concrete DAO implementation (e.g., `DictDAO` for memory, `SADAO` for
SQLAlchemy) recursively walks the Q object tree, resolves each lookup using
the provider's lookup registry, and builds a database-specific query.

`_filter` accepts a `with_total` flag (default `True`). When it is `False`
the caller only needs `ResultSet.items`, so adapters may skip an expensive
total-count computation (such as SQL's separate wrapped `COUNT` query) and
report only the size of the returned page. Adapters that derive the total for
free (memory, Elasticsearch) may continue to populate it.

`_filter` also accepts an optional `fields` argument (a list of attribute
names) set via `QuerySet.only()`. When present, the adapter fetches only those
columns (SQLAlchemy `load_only`, Elasticsearch `_source` filtering; the memory
store selects when building the result) and the QuerySet builds read-only
`Record` objects through the model's `to_records` instead of materializing
entities. Because a `Record` never enters the entity layer, the field-selection
path runs no invariants and does no event-position sync or Unit of Work
tracking, which is what keeps it cheap and the domain model uncompromised.

Counting takes a lighter path that bypasses `_filter` entirely. `count()` on
a QuerySet calls the DAO's `_count` method with just the Q object tree; the
concrete DAO issues a single `SELECT COUNT(*)` (SQLAlchemy `func.count()`,
memory `len` over the filtered set, Elasticsearch's `_count` API) with no
projection wrapper and no entity materialization. `offset`, `limit`, and
`order_by` are ignored, since none of them affect the row count.

---

## Q objects: the expression tree

Q objects (`protean.utils.query.Q`) represent filter criteria as a tree
structure. They are the internal currency that flows from QuerySet to DAO to
database.

### Tree structure

A Q object extends `Node`, which holds:

- **`children`** -- a list of leaf tuples `(field_name, value)` or nested
  `Node`/`Q` instances.
- **`connector`** -- `"AND"` or `"OR"`, determining how children are combined.
- **`negated`** -- a boolean flag that inverts the match.

```python
Q(name="John", age=3)
# Node(connector=AND, children=[("age", 3), ("name", "John")])
# Note: kwargs are sorted alphabetically
```

### Combining Q objects

Q objects support three operators that build the tree:

| Operator | Connector | Example |
|----------|-----------|---------|
| `&` | AND | `Q(a=1) & Q(b=2)` |
| `|` | OR | `Q(a=1) \| Q(b=2)` |
| `~` | Negate | `~Q(a=1)` |

Combining two Q objects creates a new parent node:

```
Q(name="John") & Q(age__gte=18)

→ Node(connector=AND)
    ├── Node(connector=AND, children=[("name", "John")])
    └── Node(connector=AND, children=[("age__gte", 18)])
```

```
Q(country="CA") | Q(country="US")

→ Node(connector=OR)
    ├── Node(connector=AND, children=[("country", "CA")])
    └── Node(connector=AND, children=[("country", "US")])
```

Negation wraps the node and flips the `negated` flag:

```
~Q(country="US")

→ Node(connector=AND, negated=True)
    └── Node(connector=AND, children=[("country", "US")])
```

### Squashing

The `Node.add()` method applies **squashing** -- when combining two nodes with
the same connector, it flattens the children into one level instead of nesting.
This keeps the tree shallow for simple AND/AND or OR/OR combinations:

```python
Q(a=1) & Q(b=2) & Q(c=3)

# Without squashing:  AND(AND(a=1, b=2), c=3)   [nested]
# With squashing:     AND(a=1, b=2, c=3)         [flat]
```

**Key source file:** `src/protean/utils/query.py`

---

## Lookup resolution

When a query uses a lookup suffix like `age__gte=18`, the system needs to
resolve `gte` into a concrete comparison operation for the target database.

### Parsing the lookup key

The provider's `_extract_lookup` method splits a composite key into the
field name and the lookup class:

```python
provider._extract_lookup("age__gte")
# → ("age", GteLookup)

provider._extract_lookup("name")
# → ("name", ExactLookup)  # default when no suffix
```

### Lookup registration

Each database provider registers its own lookup implementations using
`RegisterLookupMixin`:

```python
class SQLAlchemyProvider(BaseProvider):
    ...

# During adapter initialization:
SQLAlchemyProvider.register_lookup(ExactLookup)
SQLAlchemyProvider.register_lookup(ContainsLookup)
SQLAlchemyProvider.register_lookup(GteLookup)
# etc.
```

### BaseLookup

Every lookup extends `BaseLookup` and implements `as_expression()`:

```python
class BaseLookup:
    lookup_name: str    # e.g., "exact", "gte", "contains"

    def __init__(self, source, target):
        self.source = source   # LHS: field/column name
        self.target = target   # RHS: comparison value

    def process_source(self):
        """Transform the LHS (e.g., resolve to a column object)."""

    def process_target(self):
        """Transform the RHS (e.g., quote strings for SQL)."""

    def as_expression(self):
        """Return a database-specific filter expression."""
```

Each database adapter provides its own implementations. For example, the
memory adapter's `Exact` lookup checks Python equality, while SQLAlchemy's
`Exact` lookup produces a SQLAlchemy `column == value` expression.

Some lookups must evaluate even when the source value is absent. The `isnull`
lookup (`Q(field__isnull=True/False)`) is the canonical example: to match rows
where a field *is* `None`, the predicate has to run against a `None` source.
The memory adapter marks such lookups with a `null_safe = True` class
attribute so `_evaluate_lookup` still applies them instead of
short-circuiting when the source value is `None`. SQLAlchemy and Elasticsearch
translate `isnull` to `IS NULL` / `IS NOT NULL` and the `exists` query
respectively. `isnull` is one of the required lookups every adapter must
register, since core framework machinery such as the outbox poll path
depends on it.

By default a lookup's `target` is a literal value. An `F("other_field")`
target instead names another column of the same row, turning the predicate
into a column-to-column comparison (`retry_count < max_retries`). Each adapter
handles it in `process_target`: SQLAlchemy resolves `F` to the column object so
the comparison renders as native SQL; the memory adapter resolves it per record
to the referenced attribute; the Elasticsearch adapter raises
`NotImplementedError`, since the equivalent needs a Painless script query.
Because `F` resolution lives in `process_target`, it composes with every
comparison lookup without per-lookup changes. The outbox poll and claim paths
use `F` to push `retry_count < max_retries` into the database.

### Lookup support across adapters

Every adapter registers the same core set of lookups (`REQUIRED_LOOKUPS` on
`BaseProvider`). A provider missing one warns at load, and using it raises
`NotImplementedError`. Beyond that core set support varies, but the contract is
the same everywhere: an unsupported lookup fails loudly rather than silently
returning wrong results.

| Lookup            | Memory | SQLAlchemy        | Elasticsearch |
|-------------------|:------:|:-----------------:|:-------------:|
| `exact` / `iexact`| ✅     | ✅                | ✅            |
| `contains` / `icontains` | ✅ | ✅            | ✅            |
| `startswith` / `endswith`| ✅ | ✅            | ✅            |
| `gt` / `gte` / `lt` / `lte` | ✅ | ✅         | ✅            |
| `in`              | ✅     | ✅                | ✅            |
| `isnull`          | ✅     | ✅                | ✅            |
| `any` (array)     | ✅     | ✅ (native array) | ✅            |
| `overlap` (array) | ✅     | ✅ (native array) | ✅            |
| `F()` column ref  | ✅     | ✅                | ❌            |

The twelve lookups above `any` are universal and exercised by the cross-adapter
conformance suites under `tests/adapters/repository/generic/` and
`tests/repository/`. The array lookups `any` and `overlap` match documents whose
array field shares an element with the given values: SQLAlchemy maps them to native array operators
(`= ANY(...)` and `&&`, so they need a backend with array columns such as
PostgreSQL); Elasticsearch renders both as a `terms` query (its fields are
natively multivalued); the in-memory store evaluates a set intersection.
`F()` column references work on the memory and SQLAlchemy adapters but not on
Elasticsearch. Full-text (`search`), geospatial, and vector-similarity lookups
are backend-specific and are not part of the portable contract.

**Key source files:**

- `src/protean/port/dao.py` -- `BaseLookup` base class.
- `src/protean/utils/query.py` -- `RegisterLookupMixin`.
- `src/protean/adapters/repository/memory/` -- Memory lookup implementations.
- `src/protean/adapters/repository/sqlalchemy/` -- SQLAlchemy lookup
  implementations.

---

## Field name translation

QuerySet translates between **field names** (what domain code uses) and
**attribute names** (what the database stores). This happens transparently
in `_filter_or_exclude`:

```python
# User writes:
dao.query.filter(user_id="123")

# QuerySet resolves:
# field_name="user_id" → attribute_name="user_reference_id"
# Final criteria sent to DAO: user_reference_id="123"
```

This translation allows field names to differ from database column names
(via the `referenced_as` option on fields) without leaking persistence
concerns into query code.

The same translation applies to `order_by`:

```python
dao.query.order_by("-user_id")
# → Resolved to order_by=["-user_reference_id"]
```

---

## Indexes back the query paths

The query system decides *how* to ask; indexes decide *how fast the database
answers*. Every filter or sort beyond a primary-key lookup needs a matching
index or the database resorts to a full scan.

Protean keeps that knowledge in the domain layer: an aggregate declares the
indexes its query paths need with the `indexes=` decorator option, alongside
its fields and invariants. This mirrors the ports-and-adapters split the query
system already follows — the portable `Q`/QuerySet API on one side, the
adapter-specific SQL on the other. Portable index declarations (composite,
descending, unique) live on the aggregate and are honored by every SQL adapter;
storage-specific tuning (GIN, BRIN, expression indexes) drops to
`Index.from_sql` on the model. A partial index whose `where=` predicate is a
`Q` object reuses the very same expression tree described above, compiled to the
dialect's partial-index clause.

See [Indexes](../../reference/domain-elements/indexes.md) for the API and
[ADR-0014](../../adr/0014-aggregate-metadata-decorator-params-over-meta-class.md)
for the rationale.

---

## Lazy evaluation and caching

QuerySets use a **lazy evaluation** strategy:

1. **Building phase** -- `filter()`, `exclude()`, `limit()`, `offset()`,
   `order_by()` all clone the QuerySet and modify the clone's internal state.
   No database call occurs.

2. **Evaluation trigger** -- the database is queried only when you actually
   need data. Triggers include:
    - `.all()` -- explicit evaluation
    - `__iter__` -- `for item in queryset`
    - `__len__` -- `len(queryset)`
    - `__bool__` -- `bool(queryset)` or `if queryset:`
    - `__getitem__` -- `queryset[0]` or `queryset[1:5]`
    - `__contains__` -- `item in queryset`
    - Property access -- `.total`, `.items`, `.first`, `.last`, `.has_next`,
      `.has_prev`

3. **Caching** -- after evaluation, results are stored in `_result_cache`.
   Subsequent property access returns cached data without re-querying. Call
   `.all()` to force a fresh query (it sets `_result_cache = None` before
   querying).

---

## ResultSet

The `ResultSet` class wraps raw database results, preventing DAO-specific data
structures from leaking into the domain layer:

```python
class ResultSet:
    offset: int          # current page offset
    limit: int | None    # requested page size (None = unlimited)
    total: int           # total matching records
    items: list          # entity objects in current page

    # Properties
    has_prev → bool      # offset > 0 and items exist
    has_next → bool      # more pages exist (always False when unlimited)
    first → entity|None  # items[0] if items, else None
    last → entity|None   # items[-1] if items, else None
    page → int           # current page number (1-indexed)
    page_size → int|None # alias for limit
    total_pages → int    # math.ceil(total / limit), 0 when empty
```

The `all()` method on QuerySet converts raw database results (dicts or model
objects) into domain entity objects via `DatabaseModel.to_entity()`, marks
each entity as retrieved (`entity.state_.mark_retrieved()`), and for
aggregates, adds them to the active Unit of Work's identity map.

**Key source file:** `src/protean/core/queryset.py`

---

## ReadOnlyQuerySet

`ReadOnlyQuerySet` is a `QuerySet` subclass that blocks mutation methods.
It is returned by `domain.view_for().query` to enforce CQRS read-only access
on projections.

**Blocked methods:** `update()`, `delete()`, `update_all()`, `delete_all()`.
All raise `NotSupportedError`.

**Read methods work identically:** `filter()`, `exclude()`, `order_by()`,
`limit()`, `offset()`, `all()`, `raw()`, and all properties.

The clone-on-write pattern preserves the type — chaining `.filter()` on a
`ReadOnlyQuerySet` returns another `ReadOnlyQuerySet`, because `_clone()`
uses `self.__class__()`.

```python
# domain.view_for().query returns a ReadOnlyQuerySet
view = domain.view_for(OrderSummary)
qs = view.query

# All read operations work
results = qs.filter(status="shipped").order_by("-placed_at").limit(20).all()

# Mutation attempts raise NotSupportedError
qs.update(status="cancelled")      # raises NotSupportedError
qs.delete()                        # raises NotSupportedError
```

**Key source file:** `src/protean/core/queryset.py`

---

## Raw connection access

For queries that cannot be expressed through `QuerySet` or `ReadOnlyQuerySet`
(e.g., database-specific aggregation pipelines, full-text search, or direct
cache operations), `domain.connection_for()` provides the underlying
connection object:

```python
conn = domain.connection_for(OrderSummary)
# conn is now the raw SQLAlchemy session, Elasticsearch client,
# Redis client, etc., depending on the projection's backing store
```

This is the escape hatch — it bypasses Protean's query abstraction entirely
and hands you the technology-specific client. The method automatically routes
to the correct provider or cache based on the projection's meta options
(`provider` or `cache`).

**Key source file:** `src/protean/domain/__init__.py`

---

## Entity state tracking

When entities flow through the repository/DAO layer, their `state_` property
(an `_EntityState` instance) tracks lifecycle state:

| State | Meaning | Triggered by |
|-------|---------|-------------|
| `is_new` | Not yet persisted | Entity creation |
| `is_persisted` | Has been saved at least once | `mark_saved()` / `mark_retrieved()` |
| `is_changed` | Has unsaved modifications | `mark_changed()` (via `__setattr__`) |
| `is_destroyed` | Has been deleted | `mark_destroyed()` |

The repository uses these flags to determine persistence strategy:

- `is_new` → INSERT (via `dao.create()`)
- `is_persisted and is_changed` → UPDATE (via `dao.update()`)
- `is_persisted and not is_changed` → skip (idempotent)

**Key source file:** `src/protean/core/entity.py`

---

## Version tracking

Aggregates use a `_version` field for optimistic concurrency control. When
saving an aggregate, the DAO checks that the version in the database matches
the version on the entity. If they differ (another process updated the
aggregate in the meantime), an `ExpectedVersionError` is raised.

```python
# In BaseDAO.save():
if entity_obj._version != -1:
    # existing entity → check version
    self._validate_and_update_version(entity_obj)
```

**Key source file:** `src/protean/port/dao.py`
