# Chapter 21: Advanced Query Patterns

The storefront needs rich browsing capabilities: filter books by author,
sort by price, paginate results, and show inventory availability
alongside book information. In this chapter we will explore the full
power of `domain.query_for()` and build a cross-aggregate projection.

## ReadOnlyQuerySet Deep Dive

`domain.query_for()` returns a `ReadOnlyQuerySet` that supports:

### Filtering

```python
# Exact match
results = domain.query_for(BookCatalog).filter(author="George Orwell").all()

# Multiple conditions (AND)
results = domain.query_for(BookCatalog).filter(
    author="George Orwell",
    price__lte=15.00,
).all()
```

### Excluding

```python
# Exclude specific values
results = domain.query_for(BookCatalog).exclude(author="Unknown").all()
```

### Ordering

```python
# Ascending
results = domain.query_for(BookCatalog).order_by("price").all()

# Descending (prefix with -)
results = domain.query_for(BookCatalog).order_by("-price").all()

# Multiple fields
results = domain.query_for(BookCatalog).order_by("author", "-price").all()
```

### Pagination

```python
# First page (10 items)
page1 = domain.query_for(BookCatalog).limit(10).offset(0).all()

# Second page
page2 = domain.query_for(BookCatalog).limit(10).offset(10).all()
```

### Chaining

All methods can be chained:

```python
results = (
    domain.query_for(BookCatalog)
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
domain.query_for(BookCatalog).update(price=0)      # blocked
domain.query_for(BookCatalog).delete()              # blocked
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
