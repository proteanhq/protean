import json
import logging
from typing import Any, Optional, Union

import redis

from protean.core.projection import BaseProjection
from protean.port.cache import BaseCache
from protean.utils.inflection import underscore
from protean.utils.reflection import id_field

logger = logging.getLogger(__name__)


class RedisCache(BaseCache):
    """Redis-backed cache adapter.

    Connection pool parameters can be configured via conn_info:
        - max_connections: Maximum number of connections in the pool
        - socket_timeout: Timeout for reading from a connection in seconds
        - socket_connect_timeout: Timeout for connecting to Redis in seconds
        - retry_on_timeout: Whether to retry on timeout (default: False)
    """

    # Keys from conn_info that are forwarded to Redis connection pool
    _POOL_KEYS = frozenset(
        {
            "max_connections",
            "socket_timeout",
            "socket_connect_timeout",
            "retry_on_timeout",
        }
    )

    def __init__(self, name: str, domain: Any, conn_info: dict[str, Any]) -> None:
        """Initialize Cache with Connection/Adapter details"""

        # In case of `RedisCache`, the `cache` value will always be `redis`.
        conn_info["cache"] = "redis"
        super().__init__(name, domain, conn_info)

        pool_kwargs = {
            key: value for key, value in conn_info.items() if key in self._POOL_KEYS
        }
        self.r: "redis.Redis[Any] | None" = redis.Redis.from_url(
            conn_info["URI"], **pool_kwargs
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
        except Exception:
            logger.exception("Error closing Redis cache %s", self.name)

    def ping(self) -> bool:
        return bool(self._client.ping())

    def get_connection(self) -> "redis.Redis[Any]":
        return self._client

    def add(
        self, projection: BaseProjection, ttl: Optional[Union[int, float]] = None
    ) -> None:
        """Add projection record to cache

        KEY: Projection ID
        Value: Projection Data (derived from `to_dict()`)

        TTL is in seconds. If not specified explicitly in method call,
        it is picked up from Redis broker configuration. In the absence of
        configuration, it is set to 300 seconds.

        Args:
            projection (BaseProjection): Projection Instance containing data
            ttl (int, float, optional): Timeout in seconds. Defaults to None.
        """
        id_f = id_field(projection)
        assert id_f is not None
        assert id_f.field_name is not None
        identifier = getattr(projection, id_f.field_name)
        key = f"{underscore(projection.__class__.__name__)}:::{identifier}"

        resolved_ttl: int | float = ttl or self.conn_info.get("TTL") or 300

        # redis-py ships `py.typed` but leaves `psetex` without a return
        # annotation, so mypy --strict flags the call as untyped. Not our bug.
        self._client.psetex(  # type: ignore[no-untyped-call]
            key, int(resolved_ttl * 1000), json.dumps(projection.to_dict())
        )

    def get(self, key: str) -> Optional[BaseProjection]:
        projection_name = key.split(":::")[0]
        projection_cls = self._projections[projection_name]

        value = self._client.get(key)
        return projection_cls(json.loads(value)) if value else None

    def get_all(
        self, key_pattern: str, last_position: int = 0, size: int = 25
    ) -> list[BaseProjection]:
        projection_name = key_pattern.split(":::")[0]
        projection_cls = self._projections[projection_name]

        cursor, values = self._client.scan(
            cursor=last_position, match=key_pattern, count=size
        )
        results: list[BaseProjection] = []
        for value in values:
            raw = self._client.get(value)
            if raw is not None:
                results.append(projection_cls(json.loads(raw)))
        return results

    def count(self, key_pattern: str) -> int:
        values = self._client.scan_iter(match=key_pattern)
        return len(list(values))

    def remove(self, projection: BaseProjection) -> None:
        id_f = id_field(projection)
        assert id_f is not None
        assert id_f.field_name is not None
        identifier = getattr(projection, id_f.field_name)
        key = f"{underscore(projection.__class__.__name__)}:::{identifier}"
        self._client.delete(key)

    def remove_by_key(self, key: str) -> None:
        self._client.delete(key)

    def remove_by_key_pattern(self, key_pattern: str) -> None:
        values = self._client.scan_iter(match=key_pattern)
        self._client.delete(*values)

    def flush_all(self) -> None:
        self._client.flushall()

    def set_ttl(self, key: str, ttl: Union[int, float]) -> None:
        self._client.pexpire(key, int(ttl * 1000))

    def get_ttl(self, key: str) -> float:
        return float(self._client.pttl(key))
