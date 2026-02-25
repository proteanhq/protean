# Redis Cache

The Redis cache adapter provides persistent, distributed caching with TTL
support. It is the recommended cache provider for production environments.

## Overview

The Redis cache is designed for:

- **Production environments** requiring persistent cache storage
- **Multi-process deployments** where cache must be shared across workers
- **TTL-based expiry** with millisecond precision
- **Pattern-based operations** for bulk retrieval and cleanup

## Installation

```bash
pip install "protean[redis]"

# Or install the Redis package separately
pip install redis>=5.0.0
```

## Configuration

```toml
[caches.default]
provider = "redis"
URI = "redis://localhost:6379/2"
TTL = 300
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"redis"` for the Redis cache |
| `URI` | Required | Redis connection string |
| `TTL` | `300` | Default time-to-live in seconds |

### Connection String Format

```
redis://[[username]:[password]@]host[:port][/database]

# Examples:
redis://localhost:6379/2           # Local Redis, database 2
redis://:password@redis.prod:6379  # With password
```

!!!tip
    Use a different Redis database number (the `/2` suffix) for the cache than
    for the broker to keep concerns separated.

## Usage

Projections are automatically stored in the cache when a projector writes to a
cache-backed projection. You can also interact with the cache directly:

```python
# Get the cache instance
cache = domain.caches["default"]

# Check connectivity
cache.ping()  # Returns True if Redis is reachable

# Retrieve a cached projection
entry = cache.get("order_summary:::ord-123")

# Count cached entries
count = cache.count("order_summary:::*")

# Set a custom TTL on a specific key
cache.set_ttl("order_summary:::ord-123", ttl=600)  # 10 minutes

# Remove all entries
cache.flush_all()
```

## Limitations

- **Requires Redis Server** -- Redis must be installed and running. Use
  `make up` to start Protean's Docker-based development services.
- **Memory Bound** -- Redis stores data in memory. Ensure sufficient RAM for
  your cache working set.
- **No Complex Queries** -- The cache API supports key-based and pattern-based
  lookups only. For complex queries, use a database-backed projection instead.

## Next Steps

- Learn about [projections](../../../guides/consume-state/projections.md)
- Understand [cache configuration](../../../reference/configuration/index.md)
- Explore the [Redis broker](../broker/redis.md) for message streaming
