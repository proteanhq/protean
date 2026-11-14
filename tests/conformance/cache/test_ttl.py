"""TTL behaviour of the cache port.

Every TTL on this port is documented as seconds (`CacheTTLPort.get_ttl`), and
#1307 was exactly this suite's blind spot: each adapter's own tests asserted
their own units, and both passed. These tests read a TTL set on one adapter
back through the same assertion used for the other, so a future split fails
here instead of shipping unnoticed.

The service's handling of TTL argument shapes is tested once, on the memory
cache, in `tests/cache/test_ttl_shapes.py`.
"""

from __future__ import annotations

import time

import pytest

from protean.port.cache import CacheCapabilities

from .conftest import CacheEntry

TTL = pytest.mark.requires(CacheCapabilities.KEY_VALUE, CacheCapabilities.TTL)


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


@TTL
class TestTTLUnitsAgree:
    def test_add_with_a_ttl_reads_back_in_seconds(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"), ttl=120)

        ttl = cache.get_ttl(_key("alpha"))

        # Tolerance, not equality: the clock moves between `add` and `get_ttl`.
        assert 115 < ttl <= 120

    def test_set_ttl_reads_back_in_seconds(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        cache.set_ttl(_key("alpha"), 3000)

        ttl = cache.get_ttl(_key("alpha"))

        assert 2995 < ttl <= 3000

    def test_get_ttl_is_at_most_the_ttl_given_to_put(self, adapter):
        adapter.put("k", {"a": 1}, 120.0)

        ttl = adapter.get_ttl("k")

        assert 115 < ttl <= 120


@TTL
class TestSetTTLOnAMissingKey:
    def test_set_ttl_is_silent_when_the_key_is_absent(self, cache):
        # A neighbor must survive an absent-key `set_ttl` untouched, and the
        # absent key itself must not spring into existence as a side effect.
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.set_ttl(_key("does-not-exist"), 60)

        assert cache.get(_key("alpha")) is not None
        assert cache.get(_key("does-not-exist")) is None

    def test_set_ttl_is_silent_when_the_key_has_expired(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"), ttl=0.05)
        time.sleep(0.3)
        assert cache.get(_key("alpha")) is None

        cache.set_ttl(_key("alpha"), 60)

        assert cache.get(_key("alpha")) is None


@TTL
class TestGetTTLOnAMissingKey:
    def test_get_ttl_returns_none_for_a_missing_key(self, cache):
        assert cache.get_ttl(_key("does-not-exist")) is None

    def test_get_ttl_returns_none_for_an_expired_key(self, cache):
        # An expired-then-evicted key is absent as far as the port is
        # concerned, so `get_ttl` answers `None` for it too, matching `get`.
        # Not a stale negative number and not a raise.
        cache.add(CacheEntry(key="alpha", value="one"), ttl=0.05)
        time.sleep(0.3)
        assert cache.get(_key("alpha")) is None

        assert cache.get_ttl(_key("alpha")) is None
