"""Cache adapters. The `Cache` service and the `Caches` container live in
`protean.infra.cache`."""

from protean.infra.registry import caches as cache_registry


def register_redis() -> None:
    """Register RedisCache with Protean as the `redis` cache."""
    # Lives here, away from redis.py, so that registering the name does not
    # import redis. Without the extra installed, `get("redis")` then fails
    # naming the missing module instead of reporting an unknown name.
    cache_registry.register("redis", "protean.adapters.cache.redis.RedisCache")
