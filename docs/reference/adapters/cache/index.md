# Caches

The Cache port provides a key-value interface for storing and retrieving
projection data. Caches sit on the read side of CQRS, offering fast access to
denormalized views built by projectors.

## Overview

Protean's cache adapters store
[Projection](../../../guides/consume-state/projections.md) instances keyed by
their identifier. The `BaseCache` interface provides:

- **Add/Get/Remove** -- Store and retrieve projections by key
- **Pattern matching** -- Retrieve or remove projections by key pattern
- **TTL management** -- Set time-to-live on cached entries
- **Health checks** -- Verify cache connectivity
- **Bulk operations** -- Flush all entries

## Available Caches

### Memory

The `memory` cache is the default. It stores projections in Python dictionaries
within the process. No external dependencies are needed.

- **Use cases**: Development, testing, prototyping
- All data is lost on process restart
- No TTL enforcement (entries live until explicitly removed or process ends)

### Redis

The [Redis cache](./redis.md) provides durable, distributed caching with TTL
support.

- **Use cases**: Production environments, multi-process deployments
- **Requires**: Redis server and the `redis` Python package
- Full TTL support with millisecond precision

## Configuration

Caches are configured in the `[caches]` section of your domain configuration:

```toml
# Default: in-memory cache
[caches.default]
provider = "memory"

# Production: Redis cache
[caches.default]
provider = "redis"
URI = "redis://localhost:6379/2"
TTL = 300  # Default TTL in seconds
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `"memory"` | Cache provider (`memory` or `redis`) |
| `URI` | -- | Redis connection URI (required for Redis) |
| `TTL` | `300` | Default time-to-live in seconds |

## Interface

All cache adapters implement these methods:

| Method | Description |
|--------|-------------|
| `ping()` | Health check -- returns `True` if cache is accessible |
| `get_connection()` | Return the underlying cache connection |
| `add(projection, ttl=None)` | Store a projection with optional TTL override |
| `get(key)` | Retrieve a projection by key |
| `get_all(key_pattern, last_position, size)` | Retrieve projections matching a pattern |
| `count(key_pattern)` | Count entries matching a pattern |
| `remove(projection)` | Remove a cached projection |
| `remove_by_key(key)` | Remove an entry by key |
| `remove_by_key_pattern(key_pattern)` | Remove entries matching a pattern |
| `flush_all()` | Remove all entries |
| `set_ttl(key, ttl)` | Set a TTL on a specific key |
| `get_ttl(key)` | Get the remaining TTL on a key |

### Key Format

Cache keys follow the pattern `{projection_name}:::{identifier}`:

```
order_summary:::ord-123
user_profile:::usr-456
```

## Best Practices

1. **Always define a default cache** -- Even if it is just the memory cache
   for development.
2. **Set appropriate TTLs** -- Balance freshness against cache hit rate.
   Projections that change frequently need shorter TTLs.
3. **Use Redis in production** -- The memory cache is not suitable for
   multi-process deployments or when data must survive restarts.
4. **Monitor cache health** -- Use `cache.ping()` in your health check
   endpoints.

## Next Steps

- Learn about [Redis cache](./redis.md) for production use
- Understand [projections](../../../guides/consume-state/projections.md)
  and how they relate to caches
- Learn about [projectors](../../../guides/consume-state/projectors.md)
  that populate caches
