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

The repository speaks domain language (`add`, `get`, custom methods). The DAO
speaks database language (`_filter`, `_create`, `_update`, `_delete`). Custom
repository methods use `self._dao` to build queries and persist data.

**Key source files:**

- `src/protean/core/repository.py` -- `BaseRepository` with `add()`, `get()`,
  `_dao` property, and `_sync_children()` for cascading child entities.
- `src/protean/port/dao.py` -- `BaseDAO` with lifecycle methods (`get`,
  `find_by`, `exists`, `create`, `save`, `update`, `delete`) and abstract
  methods for concrete implementations (`_filter`, `_create`, `_update`,
  `_delete`, `_raw`).

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
    limit: int           # requested page size
    total: int           # total matching records
    items: list          # entity objects in current page

    # Properties
    has_prev → bool      # offset > 0 and items exist
    has_next → bool      # (offset + limit) < total
    first → entity|None  # items[0] if items, else None
    last → entity|None   # items[-1] if items, else None
```

The `all()` method on QuerySet converts raw database results (dicts or model
objects) into domain entity objects via `DatabaseModel.to_entity()`, marks
each entity as retrieved (`entity.state_.mark_retrieved()`), and for
aggregates, adds them to the active Unit of Work's identity map.

**Key source file:** `src/protean/core/queryset.py`

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
