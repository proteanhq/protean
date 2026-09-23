# Choosing Storage for Projections

Projections can be stored in a database (provider) or a cache. The choice depends on your query patterns, durability needs, and performance requirements.

## Database-backed (default)

```python
@domain.projection
class ProductListing:
    product_id: Identifier(identifier=True)
    name: String(max_length=200)
    price: Float()
```

By default, projections use the `"default"` database provider. This is the most common choice.

### When to use database

- Data must survive restarts (durable)
- You need complex queries (filtering, sorting, aggregation)
- The read model serves reports or dashboards
- Data volume is moderate to large

### Explicit provider

```python
@domain.projection(provider="postgres")
class ProductListing:
    ...
```

## Cache-backed

```python
@domain.projection(cache="redis")
class ActiveSession:
    session_id: Identifier(identifier=True)
    user_id: Identifier()
    email: String()
```

### When to use cache

- Data is ephemeral (sessions, real-time status)
- Read performance is critical (sub-millisecond)
- Data can be reconstructed from events if lost
- TTL-based expiration is desired

## Comparison

| Aspect | Database | Cache |
|--------|----------|-------|
| **Durability** | Persistent | Ephemeral |
| **Query flexibility** | Full SQL/ORM queries | Key-based lookup |
| **Performance** | Good | Excellent |
| **Cost** | Higher storage | Higher memory |
| **Best for** | Reports, dashboards, listings | Sessions, real-time views |

## Configuration options

| Option | Default | Purpose |
|--------|---------|---------|
| `provider` | `"default"` | Database provider name |
| `cache` | `None` | Cache provider name (overrides provider) |
| `schema_name` | auto-derived | Custom table/collection name |
| `order_by` | `()` | Default query ordering |
| `limit` | `100` | Default query result limit |

When both `provider` and `cache` are specified, `cache` takes precedence.
