"""The cache Ports: what a cache adapter implements.

A cache adapter stores JSON-ready dicts under string keys. It knows nothing
about projections: the `Cache` service in `protean.infra.cache` builds the keys,
serializes projections, rebuilds them, and resolves TTLs before it calls the
adapter.
"""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Flag, auto
from typing import TYPE_CHECKING, Any, Protocol

from protean.port.health import PoolStats

if TYPE_CHECKING:
    from protean.domain import Domain

CacheEntry = dict[str, Any]
"""The value stored under one key: whatever `BaseProjection.to_dict()` returns."""


class CacheCapabilities(Flag):
    """The behaviours a cache adapter supports.

    Each adapter declares one value through `CachePort.capabilities`. A caller
    or a conformance test reads the flag directly to learn whether the adapter
    supports a behaviour. Most adapters declare a named tier, `LOCAL` or
    `DISTRIBUTED`.
    """

    KEY_VALUE = auto()
    """Reads, writes and deletes by key, and clearing the cache: the
    `CachePort` members `get`, `put`, `delete` and `clear`, which every cache
    adapter implements."""

    TTL = auto()
    """Per-key expiry: the `CacheTTLPort` members `set_ttl` and `get_ttl`."""

    PATTERN_MATCH = auto()
    """Glob reads, counts and deletes: the `CachePatternPort` members
    `keys_matching`, `count_matching` and `delete_matching`."""

    SHARED = auto()
    """A second adapter built from the same config sees the first one's writes
    while both are open."""

    DURABLE = auto()
    """Entries survive closing the adapter and building a new one from the
    same config."""

    LOCAL = KEY_VALUE | TTL | PATTERN_MATCH
    """Key-value reads and writes, per-key expiry and glob patterns, inside
    one adapter instance."""

    DISTRIBUTED = LOCAL | SHARED | DURABLE
    """Everything in `LOCAL`, with entries shared across adapter instances and
    kept after an adapter closes."""


@dataclass(frozen=True)
class CacheHealth:
    """What `CachePort.health` reports."""

    pool: PoolStats | None
    """The adapter's connection pool, or `None` for an adapter without one."""


class CachePort(Protocol):
    """The key-value members every cache adapter implements.

    An adapter subclasses this, or a sub-protocol, explicitly. The members map
    to `CacheCapabilities.KEY_VALUE`.
    """

    name: str
    domain: "Domain"
    config: Mapping[str, Any]

    def __init__(
        self, name: str, domain: "Domain", config: Mapping[str, Any]
    ) -> None: ...

    @property
    @abstractmethod
    def capabilities(self) -> CacheCapabilities:
        """The behaviours this cache adapter supports."""
        ...

    @abstractmethod
    def ping(self) -> bool:
        """Whether the cache is reachable."""
        ...

    @abstractmethod
    def health(self) -> CacheHealth:
        """The adapter's health record."""
        ...

    @abstractmethod
    def get_connection(self) -> object:
        """The native client, or the backing store for an adapter without one."""
        ...

    def close(self) -> None:
        """Release the adapter's connections. Does nothing by default."""
        # mypy treats a Protocol member whose body is only a docstring as
        # abstract, which would make every adapter implement `close`.
        return None  # noqa: RET501

    @abstractmethod
    def clear(self) -> None:
        """Remove every entry."""
        ...

    @abstractmethod
    def get(self, key: str) -> CacheEntry | None:
        """The value stored under `key`, or `None` when the key is absent or
        has expired."""
        ...

    @abstractmethod
    def put(self, key: str, value: CacheEntry, ttl: float | None) -> None:
        """Store `value` under `key`, replacing any earlier value and expiry.

        `ttl` is a positive, finite number of seconds, or `None` for an entry
        that never expires.
        """
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove `key`. Does nothing if the key is absent."""
        ...


class CacheTTLPort(CachePort, Protocol):
    """The per-key expiry members, unlocked by `CacheCapabilities.TTL`."""

    @abstractmethod
    def set_ttl(self, key: str, ttl: float) -> None:
        """Make `key` expire `ttl` seconds from now.

        `ttl` is a positive, finite number of seconds. Does nothing if the key
        is absent.
        """
        ...

    @abstractmethod
    def get_ttl(self, key: str) -> float | None:
        """Seconds remaining before `key` expires.

        - `None` when there is no such key.
        - `math.inf` when the key exists and never expires.
        - the seconds remaining otherwise.
        """
        ...


class CachePatternPort(CachePort, Protocol):
    """The glob members, unlocked by `CacheCapabilities.PATTERN_MATCH`.

    A pattern is a glob. `*` matches any run of characters, `?` matches one,
    `[...]` is a character class, and other characters, including `.`, are
    literal. Bracket negation and escaping can differ between adapters, so
    callers keep patterns to the `name:::*` shape.
    """

    @abstractmethod
    def keys_matching(self, pattern: str) -> list[str]:
        """The distinct keys that match `pattern`, in ascending order."""
        ...

    @abstractmethod
    def count_matching(self, pattern: str) -> int:
        """The number of distinct keys that match `pattern`."""
        ...

    @abstractmethod
    def delete_matching(self, pattern: str) -> None:
        """Remove every key that matches `pattern`. Does nothing if none match."""
        ...


CAPABILITY_PORTS: dict[CacheCapabilities, type[object]] = {
    CacheCapabilities.TTL: CacheTTLPort,
    CacheCapabilities.PATTERN_MATCH: CachePatternPort,
}
"""The sub-protocol an adapter subclasses when it declares each flag.

Typed `type[object]` because mypy in strict mode rejects a Protocol with
abstract members where `type[CachePort]` is expected.
"""
