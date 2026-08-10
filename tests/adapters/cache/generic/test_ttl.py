"""Cross-adapter TTL behaviour.

Every TTL on this port is documented as seconds (`BaseCache.get_ttl`), and
#1307 was exactly this suite's blind spot: each adapter's own tests asserted
their own units, and both passed. These tests read a TTL set on one adapter
back through the same assertion used for the other, so a future split fails
here instead of shipping unnoticed.
"""

from __future__ import annotations

import math
import time

import pytest

from protean.exceptions import ConfigurationError

from .conftest import CacheEntry

REJECTED_TTLS = [
    0,
    -5,
    "nan",
    "inf",
    "not-a-number",
    True,
    False,
    float("nan"),
    float("inf"),
]
ACCEPTED_TTLS = [120, 120.5, "120", "120.5", " 120 ", "+120"]


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


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


class TestTTLShapesAreRejectedIdentically:
    """Accepted/rejected shapes both route through `_resolve_ttl`."""

    @pytest.mark.parametrize("bad_ttl", REJECTED_TTLS)
    def test_add_rejects_an_invalid_ttl(self, cache, bad_ttl):
        with pytest.raises(ConfigurationError):
            cache.add(CacheEntry(key="alpha", value="one"), ttl=bad_ttl)

    @pytest.mark.parametrize("bad_ttl", REJECTED_TTLS)
    def test_set_ttl_rejects_an_invalid_ttl(self, cache, bad_ttl):
        cache.add(CacheEntry(key="alpha", value="one"))

        with pytest.raises(ConfigurationError):
            cache.set_ttl(_key("alpha"), bad_ttl)


class TestTTLShapesAreAcceptedIdentically:
    """The other half of `TestTTLShapesAreRejectedIdentically`: the whole
    reason `str` is a valid `TTLValue` shape is env-substituted config
    (`TTL = "${CACHE_TTL|3600}"`), so a string, and specifically a string
    holding a float, must be accepted on both adapters too.
    """

    @pytest.mark.parametrize("good_ttl", ACCEPTED_TTLS)
    def test_add_accepts_a_valid_ttl(self, cache, good_ttl):
        cache.add(CacheEntry(key="alpha", value="one"), ttl=good_ttl)

        # Read back the resolved seconds, not just "something got cached":
        # a shape that mis-parses to a different-but-positive number would
        # still pass a bare `get(...) is not None` check.
        expected = float(str(good_ttl).strip())
        ttl = cache.get_ttl(_key("alpha"))
        assert expected - 5 < ttl <= expected

    @pytest.mark.parametrize("good_ttl", ACCEPTED_TTLS)
    def test_set_ttl_accepts_a_valid_ttl(self, cache, good_ttl):
        # A TTL far from every value in ACCEPTED_TTLS, so a `set_ttl` that
        # silently no-ops (and leaves this one in place) cannot pass.
        cache.add(CacheEntry(key="alpha", value="one"), ttl=3000)

        cache.set_ttl(_key("alpha"), good_ttl)

        expected = float(str(good_ttl).strip())
        ttl = cache.get_ttl(_key("alpha"))
        assert expected - 5 < ttl <= expected


class TestFailedAddLeavesNothingCached:
    """The negative test for #1304: a rejected TTL must not cache first."""

    def test_a_rejected_ttl_does_not_cache_the_projection(self, cache):
        with pytest.raises(ConfigurationError):
            cache.add(CacheEntry(key="alpha", value="one"), ttl="not-a-number")

        assert cache.get(_key("alpha")) is None


class TestSetTTLOnAMissingKey:
    def test_set_ttl_is_silent_when_the_key_is_absent(self, cache):
        # A neighbor must survive an absent-key `set_ttl` untouched, and the
        # absent key itself must not spring into existence as a side effect.
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.set_ttl(_key("does-not-exist"), 60)

        assert cache.get(_key("alpha")) is not None
        assert cache.get(_key("does-not-exist")) is None

    @pytest.mark.parametrize("bad_ttl", REJECTED_TTLS)
    def test_set_ttl_rejects_an_invalid_ttl_even_when_the_key_is_absent(
        self, cache, bad_ttl
    ):
        # TTL validation must run whether or not the key exists: Redis
        # resolves the TTL before touching the key (`_ttl_for` runs ahead of
        # `pexpire`), so an absent key does not excuse a malformed TTL.
        with pytest.raises(ConfigurationError):
            cache.set_ttl(_key("does-not-exist"), bad_ttl)

    def test_set_ttl_is_silent_when_the_key_has_expired(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"), ttl=0.05)
        time.sleep(0.3)
        assert cache.get(_key("alpha")) is None

        cache.set_ttl(_key("alpha"), 60)

        assert cache.get(_key("alpha")) is None


class TestGetTTLOnAMissingKey:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "#1392: get_ttl on a missing key should return None on every "
            "adapter. The memory cache raises KeyError and Redis returns "
            "the raw PTTL sentinel -2 instead."
        ),
    )
    def test_get_ttl_returns_none_for_a_missing_key(self, cache):
        assert cache.get_ttl(_key("does-not-exist")) is None


class TestGetTTLOnANeverExpiringKey:
    """Redis can hold a key with no expiry; the memory cache structurally
    cannot (`_resolve_ttl` never returns `None`, so `MemoryCache.__init__`
    always builds its `TTLDict` with a concrete default TTL and every entry
    gets one). A missing capability, not a disagreement, so this is skipped
    on memory rather than xfailed.
    """

    def test_get_ttl_of_a_never_expiring_key_is_math_inf(self, cache, request):
        if request.node.callspec.params["cache"]["provider"] == "memory":
            pytest.skip(
                "The memory cache cannot hold a key with no expiry: "
                "_resolve_ttl never returns None, so every entry gets a "
                "concrete default TTL. Redis can."
            )

        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                reason=(
                    "#1392: get_ttl on a never-expiring key should return "
                    "math.inf on every adapter. Redis returns the raw PTTL "
                    "sentinel -1 instead."
                ),
            )
        )

        # Bypass `add()`, which always resolves and applies a TTL, and write
        # the key directly through the raw connection so it has no expiry.
        conn = cache.get_connection()
        conn.set("cache_entry:::forever", "1")

        assert cache.get_ttl("cache_entry:::forever") == math.inf
