# Caches

The Cache port provides a key-value interface for storing and retrieving
projection data. Caches are part of the read side of CQRS. They give fast
access to the denormalized views that projectors build.

## Overview

Protean caches store
[Projection](../../../guides/consume-state/projections.md) data keyed by the
projection's identifier. Each adapter implements the `CachePort` protocol and
stores dicts under string keys. The `Cache` service that wraps it turns
projections into dicts and back, and provides:

- **Add/Get/Remove**: Store and retrieve projections by key
- **Pattern matching**: Retrieve or remove projections by key pattern
- **TTL management**: Set time-to-live on cached entries
- **Health checks**: Verify cache connectivity
- **Bulk operations**: Clear all entries

## Available Caches

### Memory

The `memory` cache is the default. It stores projections in Python dictionaries
within the process. No external dependencies are needed.

- **Use cases**: Development, testing, prototyping
- All data is lost on process restart
- TTL is enforced lazily: every entry the `Cache` service writes has an expiry.
  Reads, key matches and counts skip an expired entry. A call that names the
  key, such as `get`, `get_ttl`, `set_ttl` or `delete`, removes it. There is no
  background sweep, so an expired entry whose key no call names still occupies
  memory.

### Redis

The [Redis cache](./redis.md) provides durable, distributed caching with TTL
support.

- **Use cases**: Production environments, multi-process deployments
- **Requires**: Redis server and the `redis` Python package
- Full TTL support with millisecond precision

### Capabilities

Each cache adapter declares what it supports through its `capabilities`
property, a `CacheCapabilities` value from `protean.port.cache`. To check one
behaviour, test the flag directly, for example
`CacheCapabilities.SHARED in domain.caches["default"].capabilities`.

The memory cache declares `LOCAL`: key-value reads and writes, per-key TTLs and
glob patterns. Its entries live in one adapter instance, so a second adapter
built from the same config sees none of them. The Redis cache declares
`DISTRIBUTED`, which adds `SHARED` and `DURABLE`: every adapter built from the
same `URI` sees the same entries, and they remain after an adapter closes.

## Configuration

Caches are configured in the `[caches]` section of your domain configuration:

```toml
--8<-- "adapters/cache/index/memory.toml"
```

In production, use the Redis cache:

```toml
--8<-- "adapters/cache/index/redis.toml"
```

`${REDIS_URL|...}` reads the URI from the `REDIS_URL` environment
variable, and uses the value after `|` when it is not set.

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
--8<-- "adapters/cache/index/ttl_from_env.toml"
```

Substitution runs on TOML strings after parsing, so a TTL from the environment
arrives as a string. For this reason the cache supports the string form by
design.

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
| Key exists, no expiry set | returns `math.inf` | returns `math.inf` |

An expired entry counts as absent, so `get_ttl` returns `None` for it, the same
way `get` does. The `Cache` service passes the configured TTL with every write
to an adapter that declares `TTL`, so through the service a memory entry always
has an expiry. A key without one comes from a direct adapter write with
`ttl=None`, or on Redis from a write outside Protean.

So code reads the same on either adapter:

```python
--8<-- "adapters/cache/index/001.py:full"
```

On the memory cache, `present` is `"60s left"` and `missing` is `"missing"`.

### `_get_all` is a bounded utility, not a paged read

`_get_all(key_pattern)` returns the entries whose key matches `key_pattern`, in
key order, the same on every adapter. It is private (the leading underscore) and
deliberately unpaginated. A cache is for point reads by key; enumerating a match
set is not what it is for. On Redis, `_get_all` scans the whole keyspace, so it
is a convenience for tests and small, bounded stores, not a production read
path. `count` has the same full-scan cost. On Redis it deduplicates its scan,
so a key that `SCAN` returns more than once is counted once.

`_get_all` returns at most 1000 entries (`GET_ALL_MAX`). Past that limit, it
truncates the result to the first 1000 entries in key order and logs a warning
with the pattern and the match count. When a store grows too large for the
cache, you see that warning instead of getting a silent partial read.

To page a large projection set, query the projection's repository
(`repository_for(Projection).query`), which has indexes and native pagination.

## Interface

The `Cache` service that `domain.caches[name]` returns has these methods:

| Method | Description |
|--------|-------------|
| `ping()` | Health check, returns `True` if cache is accessible |
| `get_connection()` | Return the underlying cache connection |
| `key_for(projection_cls, identifier)` | The key of one entry, such as `order_summary:::ord-123`. See [Key Format](#key-format) |
| `pattern_for(projection_cls)` | The glob over every entry of a projection, such as `order_summary:::*` |
| `add(projection, ttl=None)` | Store a projection with optional TTL override |
| `get(key)` | Retrieve a projection by key |
| `_get_all(key_pattern)` | Private. Up to 1000 matching projections, in key order, then it truncates and warns. A bounded utility for tests and small stores, not a production read path |
| `count(key_pattern)` | Count entries matching a pattern |
| `remove(projection)` | Remove a cached projection. Does nothing if no record exists for it |
| `remove_by_key(key)` | Remove an entry by key. Does nothing if the key is absent |
| `remove_by_key_pattern(key_pattern)` | Remove entries matching a pattern. Does nothing if the pattern matches no keys |
| `clear()` | Remove every key in the cache's backing store. On Redis that is every key in the configured database |
| `set_ttl(key, ttl)` | Set a TTL on a specific key. Does nothing if the key is absent, but still rejects an invalid TTL |
| `get_ttl(key)` | Seconds remaining before a key expires; `None` if there is no such key, `math.inf` if it never expires. See below |

### Key Format

The `Cache` service builds every key. Get a key from `key_for` and a pattern
from `pattern_for`:

```python
# fragment
cache = domain.cache_for(OrderSummary)
cache.key_for(OrderSummary, "ord-123")  # "order_summary:::ord-123"
cache.pattern_for(OrderSummary)         # "order_summary:::*"
```

A key is the projection class name in snake case, then `:::`, then the
identifier formatted with `str()`. `add`, `remove` and `view_for(...).get` use
`key_for`. `view_for(...).count` and a projection rebuild use `pattern_for`.
Code that asks the service for keys needs no edit when a projection class is
renamed. The entries cached before the rename stay under the old prefix, and
reads and rebuilds of the renamed class do not see them. Clear the cache and
rebuild the projection after a rename.

The `key_pattern` on `_get_all`, `count`, and `remove_by_key_pattern` is a glob.
`*` matches any run of characters, `?` matches one, `[...]` is a character
class, and other characters are literal. Adapters agree on `*`, `?`, and
literal characters; bracket negation and escaping can differ, so pass the
pattern `pattern_for` returns.

### Methods that need a capability

Some methods need a capability the adapter may not declare. On a cache
without it, they raise `NotSupportedError` naming the cache and the flag:

| Capability | Methods |
|------------|---------|
| `TTL` | `set_ttl`, `get_ttl`, and `add` with an explicit `ttl` |
| `PATTERN_MATCH` | `_get_all`, `count`, `remove_by_key_pattern` |

`PATTERN_MATCH` also gates two callers of those methods on a cache-backed
projection. `view_for(Projection).count()` calls `count`, and
`protean projection rebuild` calls `remove_by_key_pattern` before it replays
any event. A rebuild of every projection checks the cache of each
cache-backed projection that has a projector before it truncates any
projection. `add` without a `ttl`, `get`, `remove`, `remove_by_key`, `clear`,
`key_for` and `pattern_for` work on every cache.

### Writing a cache adapter

An adapter implements the `CachePort` protocol from `protean.port.cache`. An
adapter that declares `TTL` also subclasses `CacheTTLPort`, and one that
declares `PATTERN_MATCH` also subclasses `CachePatternPort`. The
[cache port API reference](../../../api/ports/cache.md) lists the members of
each.

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
