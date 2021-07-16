import json

import redis

from protean.port.cache import BaseCache
from protean.utils import Cache
from protean.utils.inflection import underscore


class RedisCache(BaseCache):
    def __init__(self, name, domain, conn_info: dict):
        """Initialize Cache with Connection/Adapter details"""

        # In case of `MemoryCache`, the `CACHE` value will always be `MEMORY`.
        conn_info["CACHE"] = Cache.MEMORY.value
        super().__init__(name, domain, conn_info)

        self.r = redis.Redis.from_url(conn_info["URI"])

    def ping(self):
        return self.r.ping()

    def get_connection(self):
        return self.r

    def add(self, view, ttl=None):
        identifier = getattr(view, view.meta_.id_field.field_name)
        key = f"{underscore(view.__class__.__name__)}:::{identifier}"

        ttl = ttl or self.conn_info.get("TTL") or 300

        self.r.psetex(key, ttl * 1000, json.dumps(view.to_dict()))

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
        identifier = getattr(view, view.meta_.id_field.field_name)
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
