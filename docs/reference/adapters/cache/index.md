# Caches

The Cache port provides a key-value interface for storing and retrieving
projection data. Caches sit on the read side of CQRS, offering fast access to
denormalized views built by projectors.

## Overview

Protean's cache adapters store
[Projection](../../../guides/consume-state/projections.md) instances keyed by
their identifier. The `BaseCache` interface provides:

- **Add/Get/Remove**: Store and retrieve projections by key
- **Pattern matching**: Retrieve or remove projections by key pattern
- **TTL management**: Set time-to-live on cached entries
- **Health checks**: Verify cache connectivity
- **Bulk operations**: Flush all entries

## Available Caches

### Memory

The `memory` cache is the default. It stores projections in Python dictionaries
within the process. No external dependencies are needed.

- **Use cases**: Development, testing, prototyping
- All data is lost on process restart
- TTL is enforced lazily: every entry is written with an expiry, and an expired
  entry is dropped the next time it is read, iterated or counted. There is no
  background sweep, so an expired entry nobody touches still occupies memory.

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
| `URI` | —  | Redis connection URI (required for Redis) |
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
are not durations, and every adapter answers them the same way:

| State | Memory cache | Redis cache |
|-------|--------------|-------------|
| Key exists, expiry pending | seconds remaining | seconds remaining |
| No such key | returns `None` | returns `None` |
| Key exists, no expiry set | not reachable, every entry is written with one | returns `math.inf` |

An expired entry counts as absent, so `get_ttl` returns `None` for it, the same
way `get` does. `math.inf` only ever comes from Redis: the memory cache writes
every entry with a concrete TTL, so it has no never-expiring keys to report.

So code reads the same on either adapter:

```python
import math

remaining = cache.get_ttl(key)
if remaining is None:
    ...                     # no such key
elif remaining == math.inf:
    ...                     # never expires
else:
    ...                     # seconds remaining
```

### `_get_all` is a bounded utility, not a paged read

`_get_all(key_pattern)` returns every entry whose key matches `key_pattern`, in
key order, the same on every adapter. It is private (the leading underscore) and
deliberately unpaginated. A cache is for point reads by key; enumerating a match
set is not what it is for. On Redis it scans the whole keyspace and materialises
every match, so it is a convenience for tests and small, bounded stores, not a
production read path. `count` has the same full-scan cost.

To page a large projection set, query the projection's repository
(`repository_for(Projection).query`), which has indexes and native pagination.

## Interface

All cache adapters implement these methods:

| Method | Description |
|--------|-------------|
| `ping()` | Health check, returns `True` if cache is accessible |
| `get_connection()` | Return the underlying cache connection |
| `add(projection, ttl=None)` | Store a projection with optional TTL override |
| `get(key)` | Retrieve a projection by key |
| `_get_all(key_pattern)` | Private. Every matching projection, in key order. A bounded utility for tests and small stores, not a production read path |
| `count(key_pattern)` | Count entries matching a pattern |
| `remove(projection)` | Remove a cached projection. Does nothing if no record exists for it |
| `remove_by_key(key)` | Remove an entry by key. Does nothing if the key is absent |
| `remove_by_key_pattern(key_pattern)` | Remove entries matching a pattern. Does nothing if the pattern matches no keys |
| `flush_all()` | Remove all entries |
| `set_ttl(key, ttl)` | Set a TTL on a specific key. Does nothing if the key is absent, but still rejects an invalid TTL |
| `get_ttl(key)` | Seconds remaining before a key expires; `None` if there is no such key, `math.inf` if it never expires. See below |

### Key Format

Cache keys follow the pattern `{projection_name}:::{identifier}`:

```
order_summary:::ord-123
user_profile:::usr-456
```

The `key_pattern` on `_get_all`, `count`, and `remove_by_key_pattern` is a glob.
`*` matches any run of characters, `?` matches one, `[...]` is a character
class, and other characters are literal. Every entry of one projection is
`order_summary:::*`. Adapters agree on `*`, `?`, and literal characters; bracket
negation and escaping can differ, so keep patterns to the `name:::*` shape.

## Configuring a cache

1. **A default cache is required**, even if it is only the memory cache for
   development.
2. **Set appropriate TTLs**: Balance freshness against cache hit rate.
   Projections that change frequently need shorter TTLs.
3. **Use Redis in production**: The memory cache is not suitable for
   multi-process deployments or when data must survive restarts.
4. **Monitor cache health**: Use `cache.ping()` in your health check
   endpoints.

## Related pages

- Learn about [Redis cache](./redis.md) for production use
- Understand [projections](../../../guides/consume-state/projections.md)
  and how they relate to caches
- Learn about [projectors](../../../guides/consume-state/projectors.md)
  that populate caches
