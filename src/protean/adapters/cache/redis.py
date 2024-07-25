import json
from typing import Optional, Union

import redis

from protean.core.view import BaseView
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

    def add(self, view: BaseView, ttl: Optional[Union[int, float]] = None) -> None:
        """Add view record to cache

        KEY: View ID
        Value: View Data (derived from `to_dict()`)

        TTL is in seconds. If not specified explicitly in method call,
        it is picked up from Redis broker configuration. In the absence of
        configuration, it is set to 300 seconds.

        Args:
            view (BaseView): View Instance containing data
            ttl (int, float, optional): Timeout in seconds. Defaults to None.
        """
        identifier = getattr(view, id_field(view).field_name)
        key = f"{underscore(view.__class__.__name__)}:::{identifier}"

        ttl = ttl or self.conn_info.get("TTL") or 300

        self.r.psetex(key, int(ttl * 1000), json.dumps(view.to_dict()))

    def get(self, key):
        view_name = key.split(":::")[0]
        view_cls = self._views[view_name]

        value = self.r.get(key)
        return view_cls(json.loads(value)) if value else None

    def get_all(self, key_pattern, last_position=0, count=25):
        # FIXME Validate count
        view_name = key_pattern.split(":::")[0]
        view_cls = self._views[view_name]

        cursor, values = self.r.scan(
            cursor=last_position, match=key_pattern, count=count
        )
        return [view_cls(json.loads(self.r.get(value))) for value in values]

    def count(self, key_pattern, count=25):
        values = self.r.scan_iter(match=key_pattern, count=count)
        return len(list(values))

    def remove(self, view):
        identifier = getattr(view, id_field(view).field_name)
        key = f"{underscore(view.__class__.__name__)}:::{identifier}"
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
