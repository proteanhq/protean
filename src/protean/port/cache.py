from abc import ABCMeta, abstractmethod
from typing import Any

from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError
from protean.utils.inflection import underscore

DEFAULT_TTL = 300
"""Seconds a cached projection lives when the cache config sets no `TTL`."""


def _resolve_ttl(value: Any, cache_name: str) -> int | float:
    """Normalise a configured `TTL` to a number of seconds.

    A TTL that reaches here as a string is the normal case, not an edge one:
    `TTL = "${CACHE_TTL}"` substitutes to `"3600"`, because environment
    substitution runs over already-parsed TOML strings and has no type to
    restore. Left as a string it does not fail loudly. `ttl * 1000` in the Redis
    cache repeats the string a thousand times and then asks Redis to expire a
    key in a 4000-digit number of milliseconds, and the memory cache raises
    `TypeError: unsupported operand type(s) for +: 'float' and 'str'` on the
    first write. So the coercion happens once, here, where a bad value can still
    be reported against the cache that configured it.
    """
    if value is None or value == "":
        return DEFAULT_TTL
    # `bool` is an `int`, and `TTL = true` is a typo rather than one second.
    if isinstance(value, bool):
        raise ConfigurationError(
            f"Cache '{cache_name}' has TTL = {str(value).lower()}. "
            "TTL is a number of seconds."
        )
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        return int(text) if text.lstrip("+-").isdigit() else float(text)
    except (TypeError, ValueError):
        raise ConfigurationError(
            f"Cache '{cache_name}' has TTL = {value!r}, which is not a number "
            "of seconds. Set a number, or an environment variable that holds "
            'one: TTL = "${CACHE_TTL|3600}".'
        ) from None


class BaseCache(metaclass=ABCMeta):
    def __init__(self, name: str, domain: Any, conn_info: dict[str, Any]) -> None:
        """Initialize Cache with Connection/Adapter details"""
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

        self.ttl = _resolve_ttl(conn_info.get("TTL"), name)

        # Temporary cache of projections
        self._projections: dict[str, type[BaseProjection]] = {}

    def register_projection(self, projection_cls: type[BaseProjection]) -> None:
        """Registers a projection object for data serialization and de-serialization"""
        projection_name = underscore(projection_cls.__name__)
        self._projections[projection_name] = projection_cls

    def close(self) -> None:
        """Close the cache and release all connections.

        Subclasses that hold external resources (connection pools, sockets,
        etc.) should override this to perform cleanup.  The default
        implementation is a no-op so that adapters without external
        resources (e.g. the in-memory cache) work without changes.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Healthcheck to verify cache is active and accessible"""

    @abstractmethod
    def get_connection(self) -> object:
        """Get the connection object for the cache"""

    @abstractmethod
    def add(self, projection: BaseProjection, ttl: int | float | None = None) -> None:
        """Add projection record to cache

        KEY: Projection ID
        Value: Projection Data (derived from `to_dict()`)

        TTL is in seconds. If not specified explicitly in method call,
        it can be picked up from broker configuration. In the absence of
        configuration, it can be defaulted to an optimum value, say 300 seconds.

        Args:
            projection (BaseProjection): Projection Instance containing data
            ttl (int, float, optional): Timeout in seconds. Defaults to None.
        """

    @abstractmethod
    def get(self, key: str) -> BaseProjection | None:
        """Retrieve data by key"""

    @abstractmethod
    def get_all(
        self, key_pattern: str, last_position: int = 0, size: int = 25
    ) -> list[BaseProjection]:
        """Retrieve data by key pattern"""

    @abstractmethod
    def count(self, key_pattern: str) -> int:
        """Retrieve count of data by key pattern"""

    @abstractmethod
    def remove(self, projection: BaseProjection) -> None:
        """Remove a cache record by projection object"""

    @abstractmethod
    def remove_by_key(self, key: str) -> None:
        """Remove a cache record by key"""

    @abstractmethod
    def remove_by_key_pattern(self, key_pattern: str) -> None:
        """Remove a cache record by key pattern"""

    @abstractmethod
    def flush_all(self) -> None:
        """Remove all entries in Cache"""

    @abstractmethod
    def set_ttl(self, key: str, ttl: int | float) -> None:
        """Set a TTL explicitly on a key"""

    @abstractmethod
    def get_ttl(self, key: str) -> float:
        """Get the TTL set on a key"""
