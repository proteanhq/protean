import json
import logging
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import redis

from protean.port.cache import (
    CacheCapabilities,
    CacheEntry,
    CacheHealth,
    CachePatternPort,
    CachePort,
    CacheTTLPort,
)

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class RedisCache(CacheTTLPort, CachePatternPort):
    """Redis-backed cache adapter.

    Connection pool parameters can be configured via config:
        - max_connections: Maximum number of connections in the pool
        - socket_timeout: Timeout for reading from a connection in seconds
        - socket_connect_timeout: Timeout for connecting to Redis in seconds
        - retry_on_timeout: Whether to retry on timeout (default: False)
    """

    # Keys from config that are forwarded to Redis connection pool
    _POOL_KEYS = frozenset(
        {
            "max_connections",
            "socket_timeout",
            "socket_connect_timeout",
            "retry_on_timeout",
        }
    )

    # A broad pattern can match a huge number of keys. Delete them in batches
    # so no single DEL blocks Redis and the full key list never sits in memory
    # at once.
    _DELETE_BATCH_SIZE = 500

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config

        pool_kwargs = {
            key: value for key, value in config.items() if key in self._POOL_KEYS
        }
        self.r: redis.Redis[Any] | None = redis.Redis.from_url(
            config["URI"], **pool_kwargs
        )

    @property
    def _client(self) -> "redis.Redis[Any]":
        """Return the live Redis client, raising if the cache has been closed."""
        if self.r is None:
            raise RuntimeError(f"Redis cache {self.name} connection is closed")
        return self.r

    def close(self) -> None:
        """Close the Redis connection and release resources."""
        try:
            if self.r is not None:
                self.r.close()
                self.r = None
                logger.debug("Closed Redis cache connection: %s", self.name)
        except Exception:  # closing must not raise during shutdown; logged
            logger.exception("Error closing Redis cache %s", self.name)

    @property
    def capabilities(self) -> CacheCapabilities:
        """Entries live in the Redis server, so every adapter built from the
        same `URI` sees them, and they outlast the adapter that wrote them."""
        return CacheCapabilities.DISTRIBUTED

    def ping(self) -> bool:
        return bool(self._client.ping())

    def get_connection(self) -> "redis.Redis[Any]":
        return self._client

    def health(self) -> CacheHealth:
        """redis-py exposes no public counters for its connection pool, so the
        record carries no pool."""
        return CacheHealth(pool=None)

    def get(self, key: str) -> CacheEntry | None:
        value = self._client.get(key)
        if value is None:
            return None
        entry: CacheEntry = json.loads(value)
        return entry

    def put(self, key: str, value: CacheEntry, ttl: float | None) -> None:
        payload = json.dumps(value)
        if ttl is None:
            self._client.set(key, payload)
            return
        # redis-py ships `py.typed` but leaves `psetex` without a return
        # annotation, so mypy --strict flags the call as untyped. Not our bug.
        self._client.psetex(  # type: ignore[no-untyped-call]
            key, int(ttl * 1000), payload
        )

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def keys_matching(self, pattern: str) -> list[str]:
        # `SCAN` can return the same key more than once during a full iteration
        # (rehashing, concurrent writes), so dedupe before sorting.
        #
        # The keys are `bytes` (this adapter does not set `decode_responses`).
        # Sort the raw bytes, then decode: UTF-8 byte order preserves Unicode
        # code-point order, so the result is in the same order as the memory
        # adapter's `str` sort. The `Cache` service writes every key as a `str`,
        # so a key that does not decode was written by another client, and the
        # `UnicodeDecodeError` propagates.
        raw_keys = sorted(set(self._client.scan_iter(match=pattern)))
        return [key.decode("utf-8") for key in raw_keys]

    def count_matching(self, pattern: str) -> int:
        # `SCAN` can return the same key more than once, so dedupe before
        # counting, or `count_matching` would disagree with `keys_matching`.
        return len(set(self._client.scan_iter(match=pattern)))

    def delete_matching(self, pattern: str) -> None:
        # `scan_iter` yields `bytes`: this adapter does not enable
        # `decode_responses`. `delete()` takes bytes keys directly.
        batch: list[bytes] = []
        for key in self._client.scan_iter(match=pattern, count=self._DELETE_BATCH_SIZE):
            batch.append(key)
            if len(batch) >= self._DELETE_BATCH_SIZE:
                self._client.delete(*batch)
                batch.clear()
        # A pattern that matches nothing leaves `batch` empty, so no `DEL`
        # runs. `delete()` with zero keys is what Redis rejects.
        if batch:
            self._client.delete(*batch)

    def clear(self) -> None:
        """Remove every key in the configured Redis database with `FLUSHDB`.

        Cache keys carry no cache-specific namespace, so this also removes any
        other data stored in the same database. Other databases on the server are left alone.
        """
        self._client.flushdb()

    def set_ttl(self, key: str, ttl: float) -> None:
        self._client.pexpire(key, int(ttl * 1000))

    def get_ttl(self, key: str) -> float | None:
        # `PTTL` answers milliseconds. Every other TTL on this port is seconds
        # (`put`, `set_ttl`), and the memory cache returns seconds here too, so
        # convert to keep one unit across adapters.
        remaining_ms = self._client.pttl(key)

        # Two of Redis' answers are not durations: `-2` means there is no such
        # key and `-1` means the key exists with no expiry. Map them to the
        # port's shared contract by exact value. Redis only ever answers `-2`,
        # `-1`, or a non-negative duration, so any other negative is a broken
        # client: raise instead of scaling it into a misleading near-zero TTL.
        if remaining_ms == -2:
            return None
        if remaining_ms == -1:
            return math.inf
        if remaining_ms < 0:
            raise ValueError(f"Unexpected PTTL value from Redis: {remaining_ms}")
        return float(remaining_ms) / 1000


_PORT_CHECK: type[CachePort] = RedisCache
