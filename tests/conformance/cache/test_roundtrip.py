"""`add`/`get`/`clear`/`remove` round trips through the `Cache` service."""

from __future__ import annotations

import time

import pytest

from protean.port.cache import CacheCapabilities

from .conftest import CacheEntry


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


@pytest.mark.requires(CacheCapabilities.KEY_VALUE)
class TestAddThenGet:
    def test_add_then_get_round_trips(self, cache):
        entry = CacheEntry(key="alpha", value="one")
        cache.add(entry)

        fetched = cache.get(_key("alpha"))

        assert fetched == entry

    def test_get_rebuilds_the_projection_with_its_values(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))

        fetched = cache.get(_key("alpha"))

        assert isinstance(fetched, CacheEntry)
        assert (fetched.key, fetched.value) == ("alpha", "one")

    def test_get_on_a_miss_returns_none(self, cache):
        assert cache.get(_key("does-not-exist")) is None

    def test_add_overwrites_the_entry_under_the_same_key(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.add(CacheEntry(key="alpha", value="two"))

        assert cache.get(_key("alpha")).value == "two"


@pytest.mark.requires(CacheCapabilities.KEY_VALUE, CacheCapabilities.PATTERN_MATCH)
class TestFlushAll:
    def test_clear_empties_the_cache(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        cache.add(CacheEntry(key="beta", value="two"))
        assert cache.count("cache_entry:::*") == 2

        cache.clear()

        assert cache.count("cache_entry:::*") == 0
        assert cache.get(_key("alpha")) is None

    @pytest.mark.requires(CacheCapabilities.TTL)
    def test_the_cache_stays_usable_after_clear(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.clear()

        cache.add(CacheEntry(key="beta", value="two"), ttl=100)
        cache.set_ttl(_key("beta"), 200)
        assert cache.count("cache_entry:::*") == 1
        assert 190 <= cache.get_ttl(_key("beta")) <= 200


@pytest.mark.requires(CacheCapabilities.KEY_VALUE)
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

    @pytest.mark.requires(CacheCapabilities.TTL)
    def test_remove_is_silent_when_the_projection_has_expired(self, cache):
        entry = CacheEntry(key="alpha", value="one")
        cache.add(entry, ttl=0.05)
        time.sleep(0.3)
        assert cache.get(_key("alpha")) is None

        cache.remove(entry)

        assert cache.get(_key("alpha")) is None
