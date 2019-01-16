""" Module defines the Base Cache class"""
import time

# Stub class to ensure not passing in a `expriy` argument results in
# the default timeout
DEFAULT_EXPIRY = object()


class BaseCache:
    def __init__(self, params):
        expiry = params.get('expiry', params.get('EXPIRY', 300))
        if expiry is not None:
            try:
                expiry = int(expiry)
            except (ValueError, TypeError):
                expiry = 300
        self.default_expiry = expiry

        self.key_prefix = params.get('KEY_PREFIX', '')

    def get_backend_expiry(self, expiry=DEFAULT_EXPIRY):
        """
        Return the expiry value usable by this backend based upon the provided
        timeout.
        """
        if expiry == DEFAULT_EXPIRY:
            expiry = self.default_expiry
        elif expiry == 0:
            # avoid time.time() related precision issues
            expiry = -1
        return None if expiry is None else time.time() + expiry

    def make_key(self, key):
        """
        Construct the key used by all other methods. By default, prepend
        the `key_prefix'. KEY_FUNCTION can be used to specify an alternate
        function with custom key making behavior.
        """
        return f'{self.key_prefix}:{key}'

    def add(self, key, value, expiry=None):
        """
        Set a value in the cache if the key does not already exist. If
        timeout is given, use that timeout for the key; otherwise use the
        default cache timeout.
        Return True if the value was stored, False otherwise.
        """
        raise NotImplementedError(
            'subclasses of BaseCache must provide an add() method')

    def get(self, key, default=None):
        """
        Fetch a given key from the cache. If the key does not exist, return
        default, which itself defaults to None.
        """
        raise NotImplementedError(
            'subclasses of BaseCache must provide a get() method')

    def set(self, key, value, expiry=DEFAULT_EXPIRY):
        """
        Set a value in the cache. If expiry is given, use that expiry for the
        key; otherwise use the default cache timeout.
        """
        raise NotImplementedError(
            'subclasses of BaseCache must provide a set() method')

    def touch(self, key, expiry=DEFAULT_EXPIRY):
        """
        Update the key's expiry time using expiry. Return True if successful
        or False if the key does not exist.
        """
        raise NotImplementedError(
            'subclasses of BaseCache must provide a touch() method')

    def delete(self, key):
        """
        Delete a key from the cache, failing silently.
        """
        raise NotImplementedError(
            'subclasses of BaseCache must provide a delete() method')

    def get_many(self, keys):
        """
        Fetch a bunch of keys from the cache. For certain backends (memcached,
        pgsql) this can be *much* faster when fetching multiple values.
        Return a dict mapping each key in keys to its value. If the given
        key is missing, it will be missing from the response dict.
        """
        d = {}
        for k in keys:
            val = self.get(k)
            if val is not None:
                d[k] = val

        return d

    def has_key(self, key):
        """
        Return True if the key is in the cache and has not expired.
        """
        return self.get(key) is not None

    def incr(self, key, delta=1):
        """
        Add delta to value in the cache. If the key does not exist, raise a
        ValueError exception.
        """
        value = self.get(key)
        if value is None:
            raise ValueError("Key '%s' not found" % key)
        new_value = value + delta
        self.set(key, new_value)
        return new_value

    def decr(self, key, delta=1):
        """
        Subtract delta from value in the cache. If the key does not exist, raise
        a ValueError exception.
        """
        return self.incr(key, -delta)

    def set_many(self, data, expiry=DEFAULT_EXPIRY):
        """
        Set a bunch of values in the cache at once from a dict of key/value
        pairs.  For certain backends (memcached), this is much more efficient
        than calling set() multiple times.
        If timeout is given, use that timeout for the key; otherwise use the
        default cache timeout.
        On backends that support it, return a list of keys that failed
        insertion, or an empty list if all keys were inserted successfully.
        """
        for key, value in data.items():
            self.set(key, value, expiry=expiry)
        return []

    def delete_many(self, keys):
        """
        Delete a bunch of values in the cache at once. For certain backends
        (memcached), this is much more efficient than calling delete() multiple
        times.
        """
        for key in keys:
            self.delete(key)

    def clear(self):
        """Remove *all* values from the cache at once."""
        raise NotImplementedError(
            'subclasses of BaseCache must provide a clear() method')

    def close(self, **kwargs):
        """Close the cache connection"""
        pass
