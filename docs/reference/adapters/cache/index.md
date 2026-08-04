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
| `TTL` | `300` | Default time-to-live in seconds. See below. |

#### What counts as a TTL

A TTL must be a positive, finite number of seconds. It may also be a string
holding one, so an environment variable works:

```toml
[caches.default]
provider = "redis"
TTL = "${CACHE_TTL|3600}"
```

Substitution runs over already-parsed TOML strings, so a TTL sourced from the
environment arrives as a string; that is why the string form is accepted rather
than merely tolerated.

Anything else, including `0`, a negative, `nan` or `inf`, raises a
`ConfigurationError` naming the cache.

The same rule applies wherever a TTL is passed: `cache.add(projection, ttl=...)`
and `cache.set_ttl(key, ttl)` take the same shapes and reject the same ones.
Omitting the TTL (or passing an empty string) uses the cache's configured `TTL`.

### What `get_ttl` returns when there is nothing to count

`get_ttl(key)` answers the seconds remaining before a key expires. Two states
are not durations, and the adapters do not answer them the same way:

| State | Memory cache | Redis cache |
|-------|--------------|-------------|
| Key exists, expiry pending | seconds remaining | seconds remaining |
| No such key | raises `KeyError` | returns `-2` |
| Key exists, no expiry set | not reachable, every entry is written with one | returns `-1` |

Redis' `-1` and `-2` are its own documented sentinels and are passed through
unscaled: dividing them into seconds would turn flags into `-0.001` and
`-0.002`, which read as "expiring imminently" to anything comparing against
zero.

So a negative return means "not a duration". Treat it as a flag, and do not
assume a missing key behaves the same across adapters until
[#1310](https://github.com/proteanhq/protean/issues/1310) settles it.

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
| `get_ttl(key)` | Seconds remaining before a key expires. See below for how adapters answer when there is no such key |

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
