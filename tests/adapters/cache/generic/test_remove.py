"""Cross-adapter `remove_by_key` behaviour."""

from __future__ import annotations

import time

from .conftest import CacheEntry


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


class TestRemoveByKey:
    def test_remove_by_key_removes_a_present_key(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        assert cache.get(_key("alpha")) is not None

        cache.remove_by_key(_key("alpha"))

        assert cache.get(_key("alpha")) is None

    def test_remove_by_key_is_silent_when_the_key_is_absent(self, cache):
        # A neighbor must survive an absent-key `remove_by_key` untouched, so
        # an implementation that clears the whole store (or the wrong key)
        # cannot pass by accident.
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.remove_by_key(_key("does-not-exist"))

        assert cache.get(_key("alpha")) is not None

    def test_remove_by_key_is_silent_when_the_key_has_expired(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"), ttl=0.05)
        time.sleep(0.3)
        assert cache.get(_key("alpha")) is None

        cache.remove_by_key(_key("alpha"))

        assert cache.get(_key("alpha")) is None
