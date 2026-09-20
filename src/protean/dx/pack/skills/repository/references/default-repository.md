# Default Repository

Protean automatically provides a repository for every aggregate. You don't need to write any repository code to persist and load aggregates.

## Overview

When you register an aggregate with a domain, Protean dynamically constructs a repository class behind the scenes. This default repository provides two core methods:

- **`add(aggregate)`** — Persist a new aggregate or update an existing one
- **`get(identifier)`** — Load an aggregate by its identifier

This follows the DDD "collection" metaphor: a repository behaves like an in-memory collection. You `add` objects to it and `get` objects from it, without worrying about SQL, table schemas, or connection management.

## Code

The complete implementation is in [assets/repository_default.py](../assets/repository_default.py).

Key highlights:
- No `@domain.repository` decorator needed
- Access via `domain.repository_for(AggregateClass)`
- `add()` handles both creates and updates
- `get()` loads by the aggregate's identifier field

## How It Works

### Accessing the Default Repository

```python
repo = domain.repository_for(Order)
```

Protean resolves this by:
1. Checking if a custom repository is registered for `Order`
2. If not, dynamically creating an `OrderRepository` class inheriting from `BaseRepository`
3. Connecting it to the appropriate database provider

### The `add()` Method

```python
order = Order(order_id="ORD-001", customer_id="CUST-123")
repo.add(order)  # Creates the record

order.place(total_amount=99.99)
repo.add(order)  # Updates the record (same method)
```

The `add()` method:
- Checks if the aggregate is new or already persisted (via internal state tracking)
- For new aggregates: creates a new database record
- For existing aggregates: updates the existing record
- Automatically syncs child entities (HasMany/HasOne)
- Respects the active Unit of Work (if any)

### The `get()` Method

```python
order = repo.get("ORD-001")
```

The `get()` method:
- Looks up the aggregate by its identifier field
- Returns the full aggregate with all child entities loaded
- Raises `ObjectNotFoundError` if no record matches

## When You Don't Need a Custom Repository

The default repository is sufficient when:
- You only need `add()` and `get()`
- Queries are handled elsewhere (e.g., projections for read models)
- The aggregate's lifecycle is managed through commands and handlers

## When You Need a Custom Repository

Switch to a custom repository when you need:
- Domain-specific queries (e.g., `find_active_orders()`)
- Database-specific optimizations (e.g., raw SQL)
- Complex filtering beyond simple identifier lookups

See [Custom Queries](./custom-queries.md) for details.

## Related
- [Custom Queries](./custom-queries.md) - When the default isn't enough
- [Unit of Work Integration](./unit-of-work.md) - Transactional behavior
- [Anti-patterns](./anti-patterns.md) - Common mistakes
