# --8<-- [start:class]
from collections.abc import Mapping
from typing import Any

from protean import Domain
from protean.adapters.cache.memory import MemoryCache
from protean.infra.registry import caches
from protean.port.cache import (
    CacheCapabilities,
    CacheEntry,
    CacheHealth,
    CachePatternPort,
    CachePort,
    CacheTTLPort,
)


class DelegatingCache(CacheTTLPort, CachePatternPort):
    """A cache that hands every operation to the memory cache.

    Replace the delegate calls with calls to your store's client.
    """

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config
        self._delegate = MemoryCache(name, domain, config)

    @property
    def capabilities(self) -> CacheCapabilities:
        """Declare only the behaviours the store supports."""
        return self._delegate.capabilities

    # Connection and health
    def ping(self) -> bool:
        return self._delegate.ping()

    def health(self) -> CacheHealth:
        return self._delegate.health()

    def get_connection(self) -> object:
        # Open your store's client here, on the first call
        return self._delegate.get_connection()

    def close(self) -> None:
        self._delegate.close()

    # Key-value
    def clear(self) -> None:
        self._delegate.clear()

    def get(self, key: str) -> CacheEntry | None:
        return self._delegate.get(key)

    def put(self, key: str, value: CacheEntry, ttl: float | None) -> None:
        self._delegate.put(key, value, ttl)

    def delete(self, key: str) -> None:
        self._delegate.delete(key)

    # Per-key expiry, for CacheCapabilities.TTL
    def set_ttl(self, key: str, ttl: float) -> None:
        self._delegate.set_ttl(key, ttl)

    def get_ttl(self, key: str) -> float | None:
        return self._delegate.get_ttl(key)

    # Glob patterns, for CacheCapabilities.PATTERN_MATCH
    def keys_matching(self, pattern: str) -> list[str]:
        return self._delegate.keys_matching(pattern)

    def count_matching(self, pattern: str) -> int:
        return self._delegate.count_matching(pattern)

    def delete_matching(self, pattern: str) -> None:
        self._delegate.delete_matching(pattern)


# --8<-- [end:class]


# --8<-- [start:port-check]
_PORT_CHECK: type[CachePort] = DelegatingCache
# --8<-- [end:port-check]


# --8<-- [start:register]
def register() -> None:
    """Register the cache as `provider = "delegating_memory"`."""
    caches.register("delegating_memory", f"{__name__}.DelegatingCache")


# --8<-- [end:register]


# Lets a test run load the example with `-p delegating_cache`
register()
