# Query system

Protean's query system provides a database-agnostic way to filter, sort, and
paginate aggregates. This page explains the internal architecture, the layered
design, how Q objects form expression trees, how lookups are resolved by
database providers, and how QuerySets achieve lazy evaluation.

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

The repository exposes methods named in domain terms (`add`, `get`, `query`,
`find_by`, and custom methods). The DAO exposes methods named in database terms
(`_filter`, `_count`, `_create`, `_update`, `_delete`). Custom repository
methods use `self.query` and `self.find_by` (which delegate to the internal
`_dao`) to build queries.

**Where to read the code:**

- `src/protean/core/repository.py`: `BaseRepository` with `add()`, `get()`,
  `_dao` property, and `_sync_children()` for cascading child entities.
- `src/protean/port/dao.py`: `BaseDAO` with lifecycle methods (`get`,
  `find_by`, `exists`, `create`, `save`, `update`, `delete`) and abstract
  methods for concrete implementations (`_filter`, `_count`, `_create`,
  `_update`, `_delete`, `_raw`).

### DAO → QuerySet

The DAO's `.query` property returns a fresh `QuerySet` instance. The QuerySet
is the primary query-building interface:

```python
# fragment
# DAO.__init__()
self.query = QuerySet(self, domain, self.entity_cls)
```

Each QuerySet method (`filter`, `exclude`, `limit`, `offset`, `order_by`)
returns a **clone** of the QuerySet with the new criteria applied. The original
QuerySet is never mutated. Because each method returns a clone
(clone-on-write), you can chain calls safely:

```python
# fragment
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
# fragment
results = self._owner_dao._filter(
    self._criteria,     # Q object tree
    self._offset,       # int
    self._limit,        # int or None
    self._order_by      # list of strings
)
```

The concrete DAO implementation (e.g., `DictDAO` for memory, `SADAO` for
SQLAlchemy) recursively walks the Q object tree and resolves each lookup using
the provider's lookup registry. The DAO then builds a database-specific query.

`_filter` accepts a `with_total` flag (default `True`). When `with_total` is
`False`, the caller only needs `ResultSet.items`. Adapters may then skip an
expensive total-count computation (such as SQL's separate wrapped `COUNT`
query) and report only the size of the returned page. Adapters that derive the
total at no extra cost (memory, Elasticsearch) may continue to populate it.

`_filter` also accepts an optional `fields` argument (a list of attribute
names) set via `QuerySet.only()`. When `fields` is present, the adapter fetches
only those columns (SQLAlchemy `load_only`, Elasticsearch `_source` filtering;
the memory store selects when building the result). The QuerySet then builds
read-only `Record` objects through the model's `to_records` instead of
materializing entities. A `Record` never enters the entity layer, so the
field-selection path runs no invariants and does no event-position sync or Unit
of Work tracking. Skipping that work keeps the field-selection path cheap and
leaves the domain model uncompromised.

Counting takes a lighter path that bypasses `_filter` entirely. `count()` on a
QuerySet calls the DAO's `_count` method with only the Q object tree. The
concrete DAO issues a single `SELECT COUNT(*)` (SQLAlchemy `func.count()`,
memory `len` over the filtered set, Elasticsearch's `_count` API) with no
projection wrapper and no entity materialization. `count()` ignores `offset`,
`limit`, and `order_by`, since none of them change the row count.

---

## Q objects: the expression tree

Q objects (`protean.utils.query.Q`) represent filter criteria as a tree
structure. Internally, the QuerySet passes Q objects to the DAO, and the DAO
turns them into a query for the database.

### How a Q object stores its tree

A Q object extends `Node`, which holds:

- **`children`**: A list of leaf tuples `(field_name, value)` or nested
  `Node`/`Q` instances.
- **`connector`**: `"AND"` or `"OR"`, determining how children are combined.
- **`negated`**: A boolean flag that inverts the match.

```python
# fragment
Q(name="John", age=3)
# Node(connector=AND, children=[("age", 3), ("name", "John")])
# Note: kwargs are sorted alphabetically
```

### Combining Q objects

Q objects support three operators that build the tree:

| Operator | Connector | Example |
|----------|-----------|---------|
| `&` | AND | `Q(a=1) & Q(b=2)` |
| <code>&#124;</code> | OR | <code>Q(a=1) &#124; Q(b=2)</code> |
| `~` | Negate | `~Q(a=1)` |

When you combine two Q objects, Protean creates a new parent node:

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

When you negate a Q object with `~`, Protean wraps the node and flips the
`negated` flag:

```
~Q(country="US")

→ Node(connector=AND, negated=True)
    └── Node(connector=AND, children=[("country", "US")])
```

### How squashing flattens the tree

The `Node.add()` method applies **squashing**, when combining two nodes with the same
connector, it flattens the children into one level instead of nesting. This
keeps the tree shallow for simple AND/AND or OR/OR combinations:

```python
# fragment
Q(a=1) & Q(b=2) & Q(c=3)

# Without squashing:  AND(AND(a=1, b=2), c=3)   [nested]
# With squashing:     AND(a=1, b=2, c=3)         [flat]
```

**Where to read the code:** `src/protean/utils/query.py`

---

## How providers resolve lookups

When a query uses a lookup suffix like `age__gte=18`, the system needs to
resolve `gte` into a concrete comparison operation for the target database.

### Parsing the lookup key

The provider's `_extract_lookup` method splits a composite key into the
field name and the lookup class:

```python
# fragment
provider._extract_lookup("age__gte")
# → ("age", GteLookup)

provider._extract_lookup("name")
# → ("name", ExactLookup)  # default when no suffix
```

### How providers register lookups

Each database provider registers its own lookup implementations using
`RegisterLookupMixin`:

```python
# fragment
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
# fragment
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
attribute. For these lookups, `_evaluate_lookup` does not short-circuit on a
`None` source value and still applies them. SQLAlchemy and Elasticsearch
translate `isnull` to `IS NULL` / `IS NOT NULL` and the `exists` query
respectively. `isnull` is one of the required lookups every adapter must
register, since core framework machinery such as the outbox poll path depends
on it.

By default a lookup's `target` is a literal value. An `F("other_field")` target
instead names another column of the same row, turning the predicate into a
column-to-column comparison (`retry_count < max_retries`). Each adapter handles
it in `process_target`: SQLAlchemy resolves `F` to the column object so the
comparison renders as native SQL; the memory adapter resolves it per record to
the referenced attribute; the Elasticsearch adapter raises
`NotImplementedError`, since the equivalent needs a Painless script query.
Because `process_target` resolves `F`, each comparison lookup on the memory and
SQLAlchemy adapters accepts an `F` target without per-lookup changes. The
outbox poll and claim paths use `F` to push `retry_count < max_retries` into
the database.

### Which lookups each adapter supports

Every adapter registers the same core set of lookups (`REQUIRED_LOOKUPS` on
`BaseProvider`). A provider missing one warns at load, and using it raises
`NotImplementedError`. Beyond that core set, support varies by adapter. The
contract is the same on every adapter: an unsupported lookup fails loudly and
never silently returns wrong results.

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
`tests/repository/`. The array lookups `any` and `overlap` match documents
whose array field shares an element with the given values. SQLAlchemy maps them
to native array operators (`= ANY(...)` and `&&`), so they need a backend with
array columns such as PostgreSQL. Elasticsearch renders both as a `terms`
query, because its fields are natively multivalued. The in-memory store
compares elements by equality without hashing them, so it supports unhashable
items such as dicts. `F()` column references work on the memory and SQLAlchemy
adapters but not on Elasticsearch. Full-text (`search`), geospatial, and
vector-similarity lookups are backend-specific and are not part of the portable
contract.

**Where to read the code:**

- `src/protean/port/dao.py`: `BaseLookup` base class.
- `src/protean/utils/query.py`: `RegisterLookupMixin`.
- `src/protean/adapters/repository/memory/`: Memory lookup implementations.
- `src/protean/adapters/repository/sqlalchemy/`: SQLAlchemy lookup
  implementations.

---

## How QuerySet translates field names

QuerySet translates between **field names** (what domain code uses) and
**attribute names** (what the database stores). This happens transparently
in `_filter_or_exclude`:

```python
# fragment
# User writes:
dao.query.filter(user_id="123")

# QuerySet resolves:
# field_name="user_id" → attribute_name="user_reference_id"
# Final criteria sent to DAO: user_reference_id="123"
```

Because QuerySet translates the names, a field name can differ from its
database column name (via the `referenced_as` option on fields), and query code
never refers to persistence details.

The same translation applies to `order_by`:

```python
# fragment
dao.query.order_by("-user_id")
# → Resolved to order_by=["-user_reference_id"]
```

---

## Indexes back the query paths

The query system builds the query, which sets *how* to ask the database. The
indexes on the table set *how fast the database answers*. Every filter or sort
beyond a primary-key lookup needs a matching index or the database resorts to a
full scan.

Protean keeps the knowledge of which indexes a query path needs in the domain
layer. An aggregate declares the indexes its query paths need with the
`indexes=` decorator option, alongside its fields and invariants. Index
declarations follow the same ports-and-adapters split as the query system: the
portable `Q`/QuerySet API on one side, the adapter-specific SQL on the other.
You declare portable indexes (composite, descending, unique) on the aggregate,
and every SQL adapter honors them. For storage-specific tuning (GIN, BRIN,
expression indexes), you use `Index.from_sql` on the model. A partial index can
take a `Q` object as its `where=` predicate and so reuses the same expression
tree. The SQL adapter compiles that tree to the dialect's partial-index clause.

See [Indexes](../../reference/domain-elements/indexes.md) for the API, and the
decision record on aggregate metadata as decorator parameters
([ADR-0014](../../adr/0014-aggregate-metadata-decorator-params-over-meta-class.md))
for the rationale.

---

## How lazy evaluation and caching work

QuerySets use a **lazy evaluation** strategy:

1. **You build the query first**: `filter()`, `exclude()`, `limit()`,
   `offset()`, `order_by()` all clone the QuerySet and modify the clone's
   internal state. No database call occurs.

2. **Reading data runs the query**: The QuerySet queries the database only when
   you need data. Triggers include:
    - `.all()`: Explicit evaluation
    - `__iter__`: `for item in queryset`
    - `__len__`: `len(queryset)`
    - `__bool__`: `bool(queryset)` or `if queryset:`
    - `__getitem__`: `queryset[0]` or `queryset[1:5]`
    - `__contains__`: `item in queryset`
    - Property access, `.total`, `.items`, `.first`, `.last`, `.has_next`, `.has_prev`

3. **The QuerySet caches the results**: After evaluation, the QuerySet stores
   results in `_result_cache`. Subsequent property access returns cached data
   without re-querying. Call `.all()` to force a fresh query (it sets
   `_result_cache = None` before querying).

---

## ResultSet

The `ResultSet` class wraps raw database results, so DAO-specific data
structures never reach the domain layer:

```python
# fragment
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
objects) into domain entity objects via `DatabaseModel.to_entity()`. It then
marks each entity as retrieved (`entity.state_.mark_retrieved()`) and adds each
aggregate to the active Unit of Work's identity map. If the identity map
already holds an aggregate, `all()` returns the identity map's instance in
place of the newly loaded copy.

When you read a QuerySet without calling `all()` (iterating it, indexing it, or
reading `first`, `last` or `items`), the QuerySet returns a deep copy of the
cached results. Changing one result therefore does not change the next read.
Inside a Unit of Work, aggregates are the exception. A read returns the
identity map's tracked instance, the same instance that `all()` and `get()`
return. Other results, such as entities that are not aggregates, are still
copied.

A QuerySet's cache belongs to the transaction in which the QuerySet filled it.
A cache filled outside a Unit of Work belongs to no transaction. The QuerySet
runs the query again when you read it in a different transaction. Two examples
are a QuerySet evaluated before a Unit of Work began and then read inside it,
and a QuerySet read again after its Unit of Work ended. The new read returns
the data stored now. The current Unit of Work tracks the aggregates that the
new read loads.

**Key source file:** `src/protean/core/queryset.py`

---

## ReadOnlyQuerySet

`ReadOnlyQuerySet` is a `QuerySet` subclass that blocks mutation methods.
It is returned by `domain.view_for().query` to enforce CQRS read-only access
on projections.

**Blocked methods:** `update()` and `delete()`. Both raise
`NotSupportedError`.

**Read methods work identically:** `filter()`, `exclude()`, `order_by()`,
`limit()`, `offset()`, `all()`, `raw()`, and all properties.

Because `_clone()` uses `self.__class__()`, each clone keeps the type of the
QuerySet it came from. Chaining `.filter()` on a `ReadOnlyQuerySet` returns
another `ReadOnlyQuerySet`.

```python
# fragment
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

## How to get the raw connection

For queries that cannot be expressed through `QuerySet` or `ReadOnlyQuerySet`
(e.g., database-specific aggregation pipelines, full-text search, or direct
cache operations), `domain.connection_for()` provides the underlying
connection object:

```python
# fragment
conn = domain.connection_for(OrderSummary)
# conn is now the raw SQLAlchemy session, Elasticsearch client,
# Redis client, etc., depending on the projection's backing store
```

This is the escape hatch. `domain.connection_for()` skips Protean's query
abstraction entirely and returns the technology-specific client to you. The
method automatically routes to the correct provider or cache based on the
projection's meta options (`provider` or `cache`).

**Key source file:** `src/protean/domain/__init__.py`

---

## How the repository tracks entity state

When the repository/DAO layer loads or saves entities, each entity's `state_`
property (an `_EntityState` instance) tracks its lifecycle state:

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

## How the DAO checks the version

Aggregates use a `_version` field for optimistic concurrency control. When
saving an aggregate, the DAO checks that the version in the database matches
the version on the entity. If they differ (another process updated the
aggregate in the meantime), an `ExpectedVersionError` is raised.

```python
# fragment
# In BaseDAO.save():
if entity_obj._version != -1:
    # existing entity → check version
    self._validate_and_update_version(entity_obj)
```

**Key source file:** `src/protean/port/dao.py`
