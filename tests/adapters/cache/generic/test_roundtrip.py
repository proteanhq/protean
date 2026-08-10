"""Cross-adapter `add`/`get`/`flush_all`/`remove` round trips.

Each behaviour is asserted once, against whichever adapter the `cache`
fixture hands the test, so it runs against every configured cache adapter
without being duplicated per adapter.
"""

from __future__ import annotations

import time

from .conftest import CacheEntry


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


class TestAddThenGet:
    def test_add_then_get_round_trips(self, cache):
        entry = CacheEntry(key="alpha", value="one")
        cache.add(entry)

        fetched = cache.get(_key("alpha"))

        assert fetched == entry

    def test_get_on_a_miss_returns_none(self, cache):
        assert cache.get(_key("does-not-exist")) is None


class TestFlushAll:
    def test_flush_all_empties_the_cache(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        cache.add(CacheEntry(key="beta", value="two"))
        assert cache.count("cache_entry:::*") == 2

        cache.flush_all()

        assert cache.count("cache_entry:::*") == 0
        assert cache.get(_key("alpha")) is None


class TestRemoveByProjection:
    def test_remove_removes_a_present_key(self, cache):
        entry = CacheEntry(key="alpha", value="one")
        cache.add(entry)
        assert cache.get(_key("alpha")) is not None

        cache.remove(entry)

        assert cache.get(_key("alpha")) is None

    def test_remove_is_silent_when_the_projection_is_absent(self, cache):
        # A neighbor must survive an absent-projection `remove` untouched, so
        # an implementation that clears the whole store (or the wrong key)
        # cannot pass by accident.
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.remove(CacheEntry(key="does-not-exist", value="x"))

        assert cache.get(_key("alpha")) is not None

    def test_remove_is_silent_when_the_projection_has_expired(self, cache):
        entry = CacheEntry(key="alpha", value="one")
        cache.add(entry, ttl=0.05)
        time.sleep(0.3)
        assert cache.get(_key("alpha")) is None

        cache.remove(entry)

        assert cache.get(_key("alpha")) is None
