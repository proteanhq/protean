"""TTL behaviour of the cache port.

Every TTL on this port is in seconds (`CacheTTLPort.get_ttl`). Each adapter
runs the same assertions on the TTL it reads back, so an adapter that answers
in another unit fails here.

The service's handling of TTL argument shapes is tested once, on the memory
cache, in `tests/cache/test_ttl_shapes.py`.
"""

from __future__ import annotations

import math
import time

import pytest

from protean.port.cache import CacheCapabilities

from .conftest import PAST_SHORT_TTL, SHORT_TTL, CacheEntry

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

    def test_set_ttl_gives_a_never_expiring_key_an_expiry(self, adapter):
        adapter.put("k", {"a": 1}, None)

        adapter.set_ttl("k", 60.0)

        assert 55 < adapter.get_ttl("k") <= 60

    def test_put_without_a_ttl_drops_the_earlier_expiry(self, adapter):
        adapter.put("k", {"a": 1}, 60.0)

        adapter.put("k", {"a": 2}, None)

        assert adapter.get_ttl("k") == math.inf

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
        cache.add(CacheEntry(key="alpha", value="one"), ttl=SHORT_TTL)
        assert cache.get(_key("alpha")) is not None
        time.sleep(PAST_SHORT_TTL)

        # No read before `set_ttl`: a read could evict the expired entry, and
        # then this would test an absent key instead of an expired one.
        cache.set_ttl(_key("alpha"), 60)

        assert cache.get(_key("alpha")) is None


@TTL
class TestGetTTLOnAMissingKey:
    def test_get_ttl_returns_none_for_a_missing_key(self, cache):
        assert cache.get_ttl(_key("does-not-exist")) is None

    def test_get_ttl_returns_none_for_an_expired_key(self, cache):
        # An expired key is absent as far as the port is
        # concerned, so `get_ttl` answers `None` for it too, matching `get`.
        # Not a stale negative number and not a raise.
        cache.add(CacheEntry(key="alpha", value="one"), ttl=SHORT_TTL)
        assert cache.get(_key("alpha")) is not None
        time.sleep(PAST_SHORT_TTL)

        # `get_ttl` reads first, so the entry is still stored when it asks.
        assert cache.get_ttl(_key("alpha")) is None
        assert cache.get(_key("alpha")) is None
