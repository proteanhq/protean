# Chapter 21: Advanced Query Patterns

The storefront needs rich browsing capabilities: filter books by author,
sort by price, paginate results, and show inventory availability
alongside book information. In this chapter we will explore the full
power of `domain.view_for()` and build a cross-aggregate projection.

## ReadOnlyQuerySet Deep Dive

`domain.view_for()` returns a `ReadView`. Its `query` property gives
you a `ReadOnlyQuerySet` that supports:

### Filtering

```python
catalog = domain.view_for(BookCatalog)

# Exact match
results = catalog.query.filter(author="George Orwell").all()

# Multiple conditions (AND)
results = catalog.query.filter(
    author="George Orwell",
    price__lte=15.00,
).all()
```

### Excluding

```python
# Exclude specific values
results = catalog.query.exclude(author="Unknown").all()
```

### Ordering

```python
# Ascending
results = catalog.query.order_by("price").all()

# Descending (prefix with -)
results = catalog.query.order_by("-price").all()

# Multiple fields
results = catalog.query.order_by("author", "-price").all()
```

### Pagination

```python
# First page (10 items)
page1 = catalog.query.limit(10).offset(0).all()
page1.page         # 1
page1.page_size    # 10 (alias for limit)
page1.total_pages  # total pages based on matching records
page1.has_next     # True if more pages exist

# Second page
page2 = catalog.query.limit(10).offset(10).all()
page2.page         # 2
page2.has_prev     # True
```

### Chaining

All methods can be chained:

```python
results = (
    catalog.query
    .filter(author="George Orwell")
    .exclude(price__gt=20.00)
    .order_by("-price")
    .limit(10)
    .all()
)
```

### Read-Only Enforcement

`ReadOnlyQuerySet` blocks all mutation operations:

```python
# These all raise ReadOnlyQuerySetError
catalog.query.update(price=0)      # blocked
catalog.query.delete()              # blocked
```

This enforces the CQRS principle: read models are read-only. Changes
flow through commands on the write side.

## Cross-Aggregate Projections

The storefront needs a unified view showing books *with their stock
levels* — data from two aggregates (Book and Inventory).

### The StorefrontView Projection

```python
--8<-- "guides/getting-started/tutorial/ch21.py:projection"
```

### The StorefrontProjector

```python
--8<-- "guides/getting-started/tutorial/ch21.py:projector"
```

The projector subscribes to events from *both* Book and Inventory
aggregates. It maintains a single denormalized view that the storefront
can query directly.

## Enhanced API Endpoints

Update the API with rich query support:

```python
--8<-- "guides/getting-started/tutorial/ch21.py:api_endpoints"
```

Now the storefront can browse with filtering, sorting, and pagination:

```shell
# Browse all books in stock
$ curl "http://localhost:8000/storefront?in_stock=true"

# Search by author, sorted by price
$ curl "http://localhost:8000/storefront?author=Orwell&sort=-price"

# Paginate results
$ curl "http://localhost:8000/storefront?limit=10&offset=20"
```

## What We Built

- A deep understanding of **`ReadOnlyQuerySet`** — filtering, sorting,
  pagination, and read-only enforcement.
- A **`StorefrontView`** cross-aggregate projection combining Book and
  Inventory data.
- **Enhanced API endpoints** with query parameters for rich browsing.

In the final chapter, we will step back and look at the complete
architecture.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch21.py:full"
```

## Next

[Chapter 22: The Full Picture →](22-full-picture.md)
