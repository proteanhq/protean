# Projections

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Why not just query the aggregate directly? You can — but aggregates are
designed for consistency, not for read performance. Loading a full aggregate
graph just to display a dashboard row is wasteful. Projections solve this by
maintaining a separate, flattened view that is shaped for the query, not for
the write model. They're the "read side" of CQRS.

Projections are populated in response to domain events by
[projectors](./projectors.md).

## Defining a Projection

Projections are defined with the `Domain.projection` decorator.

```python hl_lines="1-2"
--8<-- "guides/consume-state/002.py:65:75"
```

### Storage Options

Projections can be stored in either a database or a cache, but not both
simultaneously:

```python
# Database storage (default)
@domain.projection(provider="postgres")
class ProductInventory:
    ...

# Cache storage
@domain.projection(cache="redis")
class ProductInventory:
    ...
```

When both `cache` and `provider` are specified, the `cache` parameter takes
precedence. See
[element decorators](../../reference/domain-elements/element-decorators.md)
for the full list of configuration options.

### Supported Field Types

Projections support basic field types (`String`, `Integer`, `Float`,
`Identifier`, `DateTime`, `Boolean`, etc.) and `ValueObject` fields.
References and Associations (`HasOne`, `HasMany`) are not supported.

ValueObject fields preserve domain semantics while being stored as flattened
shadow fields for efficient querying:

```python
@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()
    shipping_address = ValueObject(Address)  # Stored as shipping_address_street, etc.
```

You can query on individual shadow fields:

```python
results = domain.view_for(OrderSummary).query.filter(
    shipping_address_city="Springfield"
).all()
```

## Querying Projections

Use `domain.view_for()` to get a read-only interface for any projection:

```python
view = domain.view_for(ProductInventory)

# Single lookup by identifier
item = view.get("abc-123")

# Fluent filtering via ReadOnlyQuerySet
results = view.query.filter(
    stock_quantity__lt=10
).order_by("name").all()

for item in results:
    print(f"{item.name}: {item.stock_quantity} remaining")

# Convenience single-item lookup by criteria
item = view.find_by(product_id="abc-123")

# Total count and existence checks
total = view.count()
found = view.exists("abc-123")
```

The `query` property returns a `ReadOnlyQuerySet` that supports all read
operations — `filter()`, `exclude()`, `order_by()`, `limit()`, `offset()`,
and `all()` — but blocks mutations (`update`, `delete`) to enforce CQRS
read/write separation.

### Pagination

The `ResultSet` returned by `.all()` includes pagination properties:

```python
page = view.query.order_by("name").limit(20).offset(40).all()

page.items        # The actual result items
page.total        # Total matching records across all pages
page.has_next     # True if more pages exist
page.has_prev     # True if previous pages exist
page.page         # Current page number
page.page_size    # Items per page
page.total_pages  # Total number of pages
```

`ReadView` does not expose `add()`, `_dao`, or any mutation methods — it is
safe to pass to API endpoints and query handlers without risking accidental
writes.

For write operations (used inside projectors), continue using
`domain.repository_for()`:

```python
repo = domain.repository_for(ProductInventory)
repo.add(inventory_record)
```

!!! note
    `domain.view_for()` is specifically for projections. To query aggregates,
    use [repositories](../change-state/retrieve-aggregates.md) with custom
    query methods.

### Cache-backed projections

When a projection is stored in a cache (Redis, in-memory), `view.get()`,
`view.count()`, and `view.exists()` work as expected. However, `view.query`
and `view.find_by()` raise `NotSupportedError` because cache backends are
key-value stores and do not support field-based filtering.

### Three levels of projection access

Protean provides three levels of projection access, each suited to
different use cases:

| Level | Entry point | Returns | Use when |
|-------|-------------|---------|----------|
| **ReadView** | `domain.view_for(Proj)` | `ReadView` | Default for endpoints and query handlers — read-only by design |
| **Raw** | `domain.connection_for(Proj)` | DB/cache connection | Escape hatch — technology-specific queries (SQL, ES DSL, Redis) |
| **Repository** | `domain.repository_for(Proj)` | `BaseRepository` | Inside projectors — when you need to write |

### Raw connection access

When you need to run technology-specific queries that cannot be expressed
through `QuerySet` — such as SQL aggregations, Elasticsearch DSL, or Redis
`SCAN` commands — use `domain.connection_for()`:

```python
conn = domain.connection_for(OrderSummary)
# conn is the raw SQLAlchemy session, Elasticsearch client,
# Redis client, etc., depending on the projection's backing store
```

The method automatically routes to the correct provider or cache based on
the projection's configuration. For database-backed projections it returns
the database provider's connection; for cache-backed projections it returns
the cache client.

---

!!! tip "See also"
    **Concept overview:** [Projections](../../concepts/building-blocks/projections.md) — Read-optimized views in CQRS.

    **Related guides:**

    - [Projectors](./projectors.md) — How to define and configure projectors that maintain projections.
    - [Query Handlers](./query-handlers.md) — How to dispatch structured read intents via `domain.dispatch()`.
