import collections
import re
import time

from threading import RLock

try:
    # Python 3.8+
    collectionsAbc = collections.abc
except AttributeError:  # pragma: no cover
    # Until Python 3.7
    collectionsAbc = collections

from protean.port.cache import BaseCache
from protean.utils import Cache
from protean.utils.inflection import underscore


class TTLDict(collectionsAbc.MutableMapping):
    def __init__(self, default_ttl, *args, **kwargs):
        self._default_ttl = default_ttl
        self._values = {}
        self._lock = RLock()
        self.update(*args, **kwargs)

    def __repr__(self):
        return "<TTLDict@%#08x; ttl=%r, v=%r;>" % (
            id(self),
            self._default_ttl,
            self._values,
        )

    def set_ttl(self, key, ttl, now=None):
        """ Set TTL for the given key """
        if now is None:
            now = time.time()
        with self._lock:
            _expire, value = self._values[key]
            self._values[key] = (now + ttl, value)

    def get_ttl(self, key, now=None):
        """ Return remaining TTL for a key """
        if now is None:
            now = time.time()
        with self._lock:
            expire, _value = self._values[key]
            return expire - now

    def expire_at(self, key, timestamp):
        """ Set the key expire timestamp """
        with self._lock:
            _expire, value = self._values[key]
            self._values[key] = (timestamp, value)

    def is_expired(self, key, now=None, remove=False):
        """ Check if key has expired """
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

    def __len__(self):
        with self._lock:
            for key in self._values.keys():
                self.is_expired(key, remove=True)
            return len(self._values)

    def __iter__(self):
        with self._lock:
            for key in self._values.keys():
                if not self.is_expired(key):
                    yield key

    def __setitem__(self, key, value):
        with self._lock:
            if self._default_ttl is None:
                expire = None
            else:
                expire = time.time() + self._default_ttl
            self._values[key] = (expire, value)

    def __delitem__(self, key):
        with self._lock:
            del self._values[key]

    def __getitem__(self, key):
        with self._lock:
            self.is_expired(key, remove=True)
            return self._values[key][1]


class MemoryCache(BaseCache):
    def __init__(self, name, domain, conn_info: dict):
        """Initialize Cache with Connection/Adapter details"""

        # In case of `MemoryCache`, the `CACHE` value will always be `MEMORY`.
        conn_info["CACHE"] = Cache.MEMORY.value
        super().__init__(name, domain, conn_info)

        # The Data Cache
        self._db = TTLDict(self.conn_info.get("TTL") or 300)

        self._lock = RLock()

    def ping(self):
        """Always returns True for memory cache"""
        return True

    def get_connection(self):
        """Get the connection object for the repository"""
        return self._db._values

    def add(self, view, ttl=None):
        identifier = getattr(view, view.meta_.id_field.field_name)
        key = f"{underscore(view.__class__.__name__)}:::{identifier}"

        self._db[key] = view.to_dict()

        if ttl:
            self._db.set_ttl(key, ttl)

    def get(self, key):
        view_name = key.split(":::")[0]
        view_cls = self._views[view_name]

        value = self._db.get(key)
        return view_cls(value) if value else None

    def get_all(self, key_pattern, last_position=0, size=25):
        # FIXME Handle Pagination with Last Position
        # FIXME Handle Pagination with Size
        key_list = self._db.keys()
        regex = re.compile(key_pattern)
        return list(filter(regex.match, key_list))

    def count(self, key_pattern):
        key_list = self._db.keys()
        regex = re.compile(key_pattern)
        return len(list(filter(regex.match, key_list)))

    def remove(self, view):
        identifier = getattr(view, view.meta_.id_field.field_name)
        key = f"{underscore(view.__class__.__name__)}:::{identifier}"
        del self._db[key]

    def remove_by_key(self, key):
        del self._db[key]

    def remove_by_key_pattern(self, key_pattern):
        full_key_list = self._db.keys()
        regex = re.compile(key_pattern)
        keys_to_delete = list(filter(regex.match, full_key_list))
        for key in keys_to_delete:
            del self._db[key]

    def flush_all(self):
        self._db = {}

    def set_ttl(self, key, ttl):
        self._db.set_ttl(key, ttl)

    def get_ttl(self, key):
        return self._db.get_ttl(key)
