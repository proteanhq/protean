""" Module defines a Thread-safe in-memory cache backend."""

import pickle
import time
from collections import OrderedDict
from threading import Lock

from protean.core.cache.base import DEFAULT_EXPIRY
from protean.core.cache.base import BaseCache

# Global in-memory store of cache data. Keyed by name, to provide
# multiple named local memory caches.
_caches = {}
_expire_info = {}
_locks = {}


class LocalMemCache(BaseCache):
    pickle_protocol = pickle.HIGHEST_PROTOCOL

    def __init__(self, params):
        super().__init__(params)
        name = params.get('LOCATION', 'default')
        self._cache = _caches.setdefault(name, OrderedDict())
        self._expire_info = _expire_info.setdefault(name, {})
        self._lock = _locks.setdefault(name, Lock())

    def add(self, key, value, expiry=DEFAULT_EXPIRY):
        key = self.make_key(key)
        pickled = pickle.dumps(value, self.pickle_protocol)
        with self._lock:
            if self._has_expired(key):
                self._set(key, pickled, expiry)
                return True
            return False

    def get(self, key, default=None, version=None):
        key = self.make_key(key)
        with self._lock:
            if self._has_expired(key):
                self._delete(key)
                return default
            pickled = self._cache[key]
            self._cache.move_to_end(key, last=False)
        return pickle.loads(pickled)

    def _set(self, key, value, expiry=DEFAULT_EXPIRY):
        # if len(self._cache) >= self._max_entries:
        #     self._cull()
        self._cache[key] = value
        self._cache.move_to_end(key, last=False)
        self._expire_info[key] = self.get_backend_expiry(expiry)

    def set(self, key, value, expiry=DEFAULT_EXPIRY, version=None):
        key = self.make_key(key)
        pickled = pickle.dumps(value, self.pickle_protocol)
        with self._lock:
            self._set(key, pickled, expiry)

    def touch(self, key, expiry=DEFAULT_EXPIRY, version=None):
        key = self.make_key(key)
        with self._lock:
            if self._has_expired(key):
                return False
            self._expire_info[key] = self.get_backend_expiry(expiry)
            return True

    def incr(self, key, delta=1, version=None):
        key = self.make_key(key)
        with self._lock:
            if self._has_expired(key):
                self._delete(key)
                raise ValueError("Key '%s' not found" % key)
            pickled = self._cache[key]
            value = pickle.loads(pickled)
            new_value = value + delta
            pickled = pickle.dumps(new_value, self.pickle_protocol)
            self._cache[key] = pickled
            self._cache.move_to_end(key, last=False)
        return new_value

    def has_key(self, key, version=None):
        key = self.make_key(key)
        with self._lock:
            if self._has_expired(key):
                self._delete(key)
                return False
            return True

    def _has_expired(self, key):
        exp = self._expire_info.get(key, -1)
        return exp is not None and exp <= time.time()

    def _delete(self, key):
        try:
            del self._cache[key]
            del self._expire_info[key]
        except KeyError:
            pass

    def delete(self, key, version=None):
        key = self.make_key(key)
        with self._lock:
            self._delete(key)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._expire_info.clear()
