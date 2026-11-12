import collections.abc
import copy
import math
import time
from collections.abc import Iterator, Mapping
from fnmatch import fnmatchcase
from threading import RLock
from typing import TYPE_CHECKING, Any

from protean.infra.registry import caches
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


class TTLDict(collections.abc.MutableMapping[str, Any]):
    def __init__(self, default_ttl: float | None, *args: Any, **kwargs: Any) -> None:
        self._default_ttl = default_ttl
        self._values: dict[str, tuple[float | None, Any]] = {}
        self._lock = RLock()
        self.update(*args, **kwargs)

    def __repr__(self) -> str:
        return (
            f"<TTLDict@{id(self):#08x}; ttl={self._default_ttl!r}, v={self._values!r};>"
        )

    def set_ttl(self, key: str, ttl: float, now: float | None = None) -> None:
        """Make `key` expire `ttl` seconds from `now`.

        Does nothing if the key is absent or has expired. The check and the
        write run under one lock, so a concurrent delete cannot raise
        `KeyError` and an expired entry cannot come back.
        """
        with self._lock:
            # Read the clock after taking the lock: a time read before a wait
            # for the lock could treat an entry that expired meanwhile as live.
            if now is None:
                now = time.time()
            if key not in self._values or self.is_expired(key, now=now, remove=True):
                return
            _expire, value = self._values[key]
            self._values[key] = (now + ttl, value)

    def get_ttl_or_none(self, key: str) -> float | None:
        """Remaining TTL for a key, or ``None`` when it is absent or expired.

        The presence check, the eviction of a stale entry, and the read all run
        under one lock, so a concurrent eviction between the check and the read
        cannot turn a live-looking key into a `KeyError` or a stale reading.
        """
        with self._lock:
            if key not in self._values:
                return None
            now = time.time()
            if self.is_expired(key, now=now, remove=True):
                return None
            expire, _value = self._values[key]
            # A `None` expiry is a never-expiring entry: one written with no
            # TTL. Report it as `math.inf`, the port's shared answer.
            if expire is None:
                return math.inf
            return expire - now

    def put(self, key: str, value: Any, ttl: float | None) -> None:
        """Store `value` under `key`, expiring `ttl` seconds from now, or never
        when `ttl` is `None`.

        The value and its expiry are written in one step, so no reader sees the
        new value with the old expiry.
        """
        with self._lock:
            expire = None if ttl is None else time.time() + ttl
            self._values[key] = (expire, value)

    def expire_at(self, key: str, timestamp: float) -> None:
        """Set the key expire timestamp"""
        with self._lock:
            _expire, value = self._values[key]
            self._values[key] = (timestamp, value)

    def is_expired(
        self, key: str, now: float | None = None, remove: bool = False
    ) -> bool:
        """Check if key has expired"""
        with self._lock:
            if now is None:
                now = time.time()
            expire, _value = self._values[key]
            if expire is None:
                return False
            expired = expire < now
            if expired and remove:
                self.__delitem__(key)
            return expired

    def __len__(self) -> int:
        with self._lock:
            for key in list(self._values.keys()):
                self.is_expired(key, remove=True)
            return len(self._values)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            for key in self._values:
                if not self.is_expired(key):
                    yield key

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            expire: float | None
            if self._default_ttl is None:
                expire = None
            else:
                expire = time.time() + self._default_ttl
            self._values[key] = (expire, value)

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._values[key]

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            self.is_expired(key, remove=True)
            return self._values[key][1]


class MemoryCache(CacheTTLPort, CachePatternPort):
    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config

        # No default expiry: the `Cache` service passes every entry's TTL to `put`.
        self._db = TTLDict(None)

    @property
    def capabilities(self) -> CacheCapabilities:
        """Entries live in a `TTLDict` inside this adapter instance, so a
        second adapter sees none of them and a new adapter starts empty."""
        return CacheCapabilities.LOCAL

    def ping(self) -> bool:
        """Always returns True for memory cache"""
        return True

    def health(self) -> CacheHealth:
        """The memory cache has no connection pool."""
        return CacheHealth(pool=None)

    def get_connection(self) -> object:
        """The dict that backs this cache."""
        return self._db._values

    def clear(self) -> None:
        self._db.clear()

    def get(self, key: str) -> CacheEntry | None:
        # Copy on the way in and out, so a caller that changes a dict it
        # passed to `put` or got from `get` does not change the stored entry.
        # The Redis adapter gets the same isolation from its JSON round trip.
        value: CacheEntry | None = self._db.get(key)
        return None if value is None else copy.deepcopy(value)

    def put(self, key: str, value: CacheEntry, ttl: float | None) -> None:
        self._db.put(key, copy.deepcopy(value), ttl)

    def delete(self, key: str) -> None:
        self._db.pop(key, None)

    def set_ttl(self, key: str, ttl: float) -> None:
        self._db.set_ttl(key, ttl)

    def get_ttl(self, key: str) -> float | None:
        # A never-added key and an expired-but-not-yet-evicted key both answer
        # `None`, matching how `get` already treats them. The check and the read
        # are one locked operation, so a concurrent eviction cannot reintroduce
        # a `KeyError`.
        return self._db.get_ttl_or_none(key)

    def _matching(self, pattern: str) -> list[str]:
        # Snapshot with list() so the matching runs outside the store's lock:
        # keys() is a lazy iterator that holds TTLDict's RLock for the whole
        # traversal, so matching while iterating it would hold the lock across
        # every fnmatch call.
        key_list = list(self._db.keys())
        return [key for key in key_list if fnmatchcase(key, pattern)]

    def keys_matching(self, pattern: str) -> list[str]:
        return sorted(self._matching(pattern))

    def count_matching(self, pattern: str) -> int:
        return len(self._matching(pattern))

    def delete_matching(self, pattern: str) -> None:
        # A key can expire between the scan and this delete, so use `pop` with
        # a default.
        for key in self._matching(pattern):
            self._db.pop(key, None)


def register() -> None:
    """Register MemoryCache with Protean as the `memory` cache."""
    caches.register("memory", "protean.adapters.cache.memory.MemoryCache")


_PORT_CHECK: type[CachePort] = MemoryCache
