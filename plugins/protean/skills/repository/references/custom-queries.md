# Custom Queries

Custom repositories extend the default repository with domain-specific query methods. These methods encapsulate database interactions behind meaningful domain names.

## Overview

While the default repository provides `add()` and `get()`, real applications need richer queries: finding orders by status, searching products by category, looking up users by email, etc. Custom repositories are the place for these domain-specific queries.

In DDD, repositories serve as the boundary between the domain model and the persistence layer. All database-specific logic — SQL, NoSQL queries, index usage, performance optimizations — is encapsulated inside repository methods.

## Code

The complete implementation is in [assets/repository_custom.py](../assets/repository_custom.py).

Key highlights:
- Custom repository defined with `@domain.repository(part_of=Aggregate)`
- Query methods use the public helpers `self.query`, `self.find_by()`, `self.find()`, and `self.exists()`
- `self.query.filter()` for building queries
- Methods return domain objects, not raw database records

## The query interface

Inside a custom repository, `self.query` returns a `QuerySet` for fluent filtering, ordering, and pagination. Use `self.find_by()` to load a single aggregate, `self.find()` to run a composable `Q` expression, and `self.exists()` to test whether a match exists. `self._dao` remains available as an internal escape hatch for infrastructure work (hard deletion, test teardown), so reach for the public helpers in routine domain queries.

### Basic Filtering

```python
@domain.repository(part_of=Product)
class ProductRepository:
    def find_by_category(self, category):
        return self.query.filter(category=category).all()
```

### Filter Operators

The query interface supports Django-style lookups:

| Operator | Example | SQL Equivalent |
|----------|---------|----------------|
| `exact` (default) | `filter(name="Widget")` | `WHERE name = 'Widget'` |
| `__lt` | `filter(price__lt=100)` | `WHERE price < 100` |
| `__lte` | `filter(price__lte=100)` | `WHERE price <= 100` |
| `__gt` | `filter(price__gt=50)` | `WHERE price > 50` |
| `__gte` | `filter(price__gte=50)` | `WHERE price >= 50` |
| `__in` | `filter(status__in=["active", "pending"])` | `WHERE status IN (...)` |
| `__contains` | `filter(name__contains="widget")` | `WHERE name LIKE '%widget%'` |

### Chaining Filters

```python
def find_active_electronics(self):
    return (
        self.query
        .filter(category="electronics")
        .filter(is_active=True)
        .all()
    )
```

### Ordering

```python
def find_cheapest(self, limit=10):
    return (
        self.query
        .order_by("price")
        .limit(limit)
        .all()
    )
```

### Finding Single Objects

```python
def find_by_email(self, email):
    """Find a user by email. Raises ObjectNotFoundError if not found."""
    return self.find_by(email=email)
```

`find_by()` raises `ObjectNotFoundError` if no record matches and `TooManyObjectsError` if multiple records match.

## Naming Conventions

Use domain-meaningful names for repository methods:

| Good | Bad |
|------|-----|
| `find_active_orders()` | `get_by_status_active()` |
| `find_by_customer(customer_id)` | `query_where_customer_eq(id)` |
| `find_overdue()` | `select_status_overdue_from_orders()` |
| `find_affordable(max_price)` | `filter_price_lte(price)` |

## Custom Repositories Still Have Base Methods

Custom repositories inherit from `BaseRepository`, so they still have `add()` and `get()`:

```python
repo = domain.repository_for(Product)
repo.add(product)              # Inherited from BaseRepository
repo.get("PROD-001")           # Inherited from BaseRepository
repo.find_by_category("books") # Custom method
```

## Raw Queries

For a database-specific filter that still returns whole aggregates, use `self.query.raw()`. It hydrates every row it gets back into a full aggregate, so the query has to select whole rows. The table you name is the aggregate's `schema_name`, which defaults to the underscored class name (`report` for `Report`):

```python
@domain.repository(part_of=Report)
class ReportRepository:
    def find_high_value(self):
        """Use a raw query for a filter the query interface cannot express."""
        return self.query.raw(
            "SELECT * FROM report WHERE total_value > 10000"
        )
```

A result that cannot become an aggregate, such as an aggregation or a two-column summary, needs the provider-level `raw()` instead. It hands back the rows as the database returned them. Look the provider up through the aggregate's own `meta_.provider`, so the query runs against the database the repository is wired to:

```python
from protean.utils.globals import current_domain

@domain.repository(part_of=Report)
class ReportRepository:
    def find_summary_stats(self):
        """Aggregate in the database and read the rows back as they come."""
        return current_domain.providers[Report.meta_.provider].raw(
            "SELECT report_type, SUM(total_value) FROM report GROUP BY report_type"
        )
```

**Note**: Raw queries bypass the query interface. Use them sparingly and only when the standard query interface is insufficient.

## Related
- [Default Repository](./default-repository.md) - The auto-generated repository
- [Database-Specific Repositories](./database-specific.md) - Per-database query optimizations
- [Anti-patterns](./anti-patterns.md) - Common mistakes with custom queries
