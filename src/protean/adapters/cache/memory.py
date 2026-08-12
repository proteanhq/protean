import collections.abc
import math
import time
from collections.abc import Iterator
from fnmatch import fnmatchcase
from threading import RLock
from typing import Any

from protean.core.projection import BaseProjection
from protean.port.cache import BaseCache, TTLValue
from protean.utils.inflection import underscore
from protean.utils.reflection import id_field


class TTLDict(collections.abc.MutableMapping[str, Any]):
    def __init__(
        self, default_ttl: int | float | None, *args: Any, **kwargs: Any
    ) -> None:
        self._default_ttl = default_ttl
        self._values: dict[str, tuple[float | None, Any]] = {}
        self._lock = RLock()
        self.update(*args, **kwargs)

    def __repr__(self) -> str:
        return (
            f"<TTLDict@{id(self):#08x}; ttl={self._default_ttl!r}, v={self._values!r};>"
        )

    def set_ttl(self, key: str, ttl: int | float, now: float | None = None) -> None:
        """Set TTL for the given key"""
        if now is None:
            now = time.time()
        with self._lock:
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
            # A `None` expiry is a never-expiring entry (a `TTLDict` built with
            # `default_ttl=None`). `MemoryCache` never does this, but `TTLDict`
            # allows it, so report it as `math.inf`, the port's shared answer.
            if expire is None:
                return math.inf
            return expire - now

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


class MemoryCache(BaseCache):
    def __init__(self, name: str, domain: Any, conn_info: dict[str, Any]) -> None:
        """Initialize Cache with Connection/Adapter details"""

        # In case of `MemoryCache`, the `cache` value will always be `memory`.
        conn_info["cache"] = "memory"
        super().__init__(name, domain, conn_info)

        # The Data Cache
        self._db = TTLDict(self.ttl)

        self._lock = RLock()

    def ping(self) -> bool:
        """Always returns True for memory cache"""
        return True

    def get_connection(self) -> object:
        """Get the connection object for the repository"""
        return self._db._values

    def add(self, projection: BaseProjection, ttl: TTLValue | None = None) -> None:
        """Add projection record to cache

        KEY: Projection ID
        Value: Projection Data (derived from `to_dict()`)

        TTL is in seconds. Accepts a number, or a string holding one, because a
        TTL sourced from config arrives as a string: environment substitution
        runs over already-parsed TOML strings. Anything that is not a positive,
        finite number of seconds raises a `ConfigurationError` naming the cache.

        Omitted (or an empty string) means "use this cache's `TTL`", which falls
        back to 300 seconds when the cache configures none.

        Args:
            projection (BaseProjection): Projection Instance containing data
            ttl (int, float, str, optional): Timeout in seconds. Defaults to None.
        """
        id_f = id_field(projection)
        assert id_f is not None
        assert id_f.field_name is not None
        identifier = getattr(projection, id_f.field_name)
        key = f"{underscore(projection.__class__.__name__)}:::{identifier}"

        # Resolved before the write, so a bad TTL raises without leaving a
        # cached entry behind. The Redis adapter already had this ordering.
        explicit_ttl = self._explicit_ttl(ttl)

        self._db[key] = projection.to_dict()

        # Only when the caller actually named one. Left out, the store applies
        # this cache's TTL on insert, so re-setting it here would restart the
        # countdown and make `ttl=""` behave differently from omitting it.
        if explicit_ttl is not None:
            self._db.set_ttl(key, explicit_ttl)

    def get(self, key: str) -> BaseProjection | None:
        projection_name = key.split(":::")[0]
        projection_cls = self._projections[projection_name]

        value = self._db.get(key)
        return projection_cls(value) if value else None

    def get_all(
        self, key_pattern: str, last_position: int = 0, size: int = 25
    ) -> list[BaseProjection]:
        projection_name = key_pattern.split(":::")[0]
        projection_cls = self._projections[projection_name]

        # Snapshot with list() so the matching below runs outside the store's
        # lock: keys() is a lazy iterator that holds TTLDict's RLock for the
        # whole traversal, so matching while iterating it would hold the lock
        # across every fnmatch call.
        key_list = list(self._db.keys())
        # Sort so `last_position` is a stable offset into a fixed order rather
        # than insertion order. Both adapters page over keys sorted ascending,
        # so the same offset names the same entry on memory and Redis.
        results = sorted(key for key in key_list if fnmatchcase(key, key_pattern))

        # Apply pagination
        page = self._page(results, last_position, size)

        # A key can expire between the scan above and this read, so a `get`
        # can come back empty. Skip it, the same way the Redis adapter does.
        return [
            projection_cls(value)
            for key in page
            if (value := self._db.get(key)) is not None
        ]

    def count(self, key_pattern: str) -> int:
        # list() snapshots under the store's lock; matching then runs lock-free.
        key_list = list(self._db.keys())
        return sum(1 for key in key_list if fnmatchcase(key, key_pattern))

    def remove(self, projection: BaseProjection) -> None:
        id_f = id_field(projection)
        assert id_f is not None
        assert id_f.field_name is not None
        identifier = getattr(projection, id_f.field_name)
        key = f"{underscore(projection.__class__.__name__)}:::{identifier}"
        self._db.pop(key, None)

    def remove_by_key(self, key: str) -> None:
        self._db.pop(key, None)

    def remove_by_key_pattern(self, key_pattern: str) -> None:
        # list() snapshots under the store's lock; matching then runs lock-free.
        key_list = list(self._db.keys())
        keys_to_delete = [key for key in key_list if fnmatchcase(key, key_pattern)]
        # A key can expire between the scan above and this delete, so use
        # `pop` with a default, the same as `remove` and `remove_by_key`.
        for key in keys_to_delete:
            self._db.pop(key, None)

    def flush_all(self) -> None:
        # Clear in place so the TTLDict (and its configured default TTL) is
        # preserved — reassigning a plain {} broke set_ttl/get_ttl afterwards.
        self._db.clear()

    def set_ttl(self, key: str, ttl: TTLValue) -> None:
        resolved_ttl = self._ttl_for(ttl)
        if key in self._db:
            self._db.set_ttl(key, resolved_ttl)

    def get_ttl(self, key: str) -> float | None:
        # A never-added key and an expired-but-not-yet-evicted key both answer
        # `None`, matching how `get` already treats them. The check and the read
        # are one locked operation, so a concurrent eviction cannot reintroduce
        # the `KeyError` this contract removes. `math.inf` (no expiry) is
        # unreachable on this adapter: `MemoryCache` always builds its `TTLDict`
        # with a concrete default TTL, so every entry has an expiry.
        return self._db.get_ttl_or_none(key)
