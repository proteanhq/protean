# Chapter 21: Advanced Query Patterns

The storefront needs rich browsing capabilities: filter books by author,
sort by price, paginate results, and show inventory availability
alongside book information. In this chapter we will explore the full
range of `domain.view_for()` and build a cross-aggregate projection.

## ReadOnlyQuerySet in detail

`domain.view_for()` returns a `ReadView`. Its `query` property gives
you a `ReadOnlyQuerySet`. The examples below query the `StorefrontView`
projection that we build later in this chapter. Each one is a small function
that takes the view as `catalog`. The `ReadOnlyQuerySet` supports:

### Filtering

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:filtering"
```

### Excluding

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:excluding"
```

### Ordering

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:ordering"
```

### Pagination

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:pagination"
```

### Chaining

All methods can be chained:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:chaining"
```

### Read-Only Enforcement

`ReadOnlyQuerySet` blocks all mutation operations. Both calls below raise
`NotSupportedError`:

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:read_only"
```

This enforces the CQRS principle: read models are read-only. Changes
flow through commands on the write side.

## Cross-Aggregate Projections

The storefront needs a unified view showing books *with their stock
levels*, data from two aggregates (Book and Inventory).

### The StorefrontView Projection

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:projection"
```

### The StorefrontProjector

```python
# fragment
--8<-- "guides/getting-started/tutorial/ch21.py:projector"
```

The projector subscribes to events from *both* Book and Inventory
aggregates. It maintains a single denormalized view that the storefront
can query directly.

## Enhanced API Endpoints

Update the API with rich query support:

```python
# fragment
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

- A deep understanding of **`ReadOnlyQuerySet`**, filtering, sorting, pagination, and
  read-only enforcement.
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
