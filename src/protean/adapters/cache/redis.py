import json
from typing import Optional, Union

import redis

from protean.core.projection import BaseProjection
from protean.port.cache import BaseCache
from protean.utils.inflection import underscore
from protean.utils.reflection import id_field


class RedisCache(BaseCache):
    def __init__(self, name, domain, conn_info: dict):
        """Initialize Cache with Connection/Adapter details"""

        # FIXME Update cache value to REDIS
        # In case of `RedisCache`, the `cache` value will always be `redis`.
        conn_info["cache"] = "redis"
        super().__init__(name, domain, conn_info)

        self.r = redis.Redis.from_url(conn_info["URI"])

    def ping(self):
        return self.r.ping()

    def get_connection(self):
        return self.r

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
        identifier = getattr(projection, id_field(projection).field_name)
        key = f"{underscore(projection.__class__.__name__)}:::{identifier}"

        ttl = ttl or self.conn_info.get("TTL") or 300

        self.r.psetex(key, int(ttl * 1000), json.dumps(projection.to_dict()))

    def get(self, key):
        projection_name = key.split(":::")[0]
        projection_cls = self._projections[projection_name]

        value = self.r.get(key)
        return projection_cls(json.loads(value)) if value else None

    def get_all(self, key_pattern, last_position=0, count=25):
        # FIXME Validate count
        projection_name = key_pattern.split(":::")[0]
        projection_cls = self._projections[projection_name]

        cursor, values = self.r.scan(
            cursor=last_position, match=key_pattern, count=count
        )
        return [projection_cls(json.loads(self.r.get(value))) for value in values]

    def count(self, key_pattern, count=25):
        values = self.r.scan_iter(match=key_pattern, count=count)
        return len(list(values))

    def remove(self, projection):
        identifier = getattr(projection, id_field(projection).field_name)
        key = f"{underscore(projection.__class__.__name__)}:::{identifier}"
        self.r.delete(key)

    def remove_by_key(self, key):
        self.r.delete(key)

    def remove_by_key_pattern(self, key_pattern):
        values = self.r.scan_iter(match=key_pattern)
        self.r.delete(*values)

    def flush_all(self):
        self.r.flushall()

    def set_ttl(self, key, ttl):
        self.r.pexpire(key, ttl * 1000)

    def get_ttl(self, key):
        return self.r.pttl(key)
