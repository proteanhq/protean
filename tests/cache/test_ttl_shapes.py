"""The TTL argument shapes the `Cache` service accepts and rejects.

The service resolves every TTL before it calls the adapter, so these tests run
once, on the memory cache. The cache is configured with an hour-long `TTL`, far
from `DEFAULT_TTL`, so a test can tell the configured TTL from the default.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String

CONFIGURED_TTL = 3600

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

# The `cache` fixture builds its own domain with the configured `TTL`.
pytestmark = pytest.mark.no_test_domain


class CacheEntry(BaseProjection):
    key: Identifier(identifier=True)
    value: String(required=True)


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


@pytest.fixture
def cache():
    domain = Domain(name="Test")
    domain.config["caches"]["default"] = {"provider": "memory", "TTL": CONFIGURED_TTL}
    domain.register(CacheEntry)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain.cache_for(CacheEntry)


class TestTTLShapesAreRejected:
    @pytest.mark.parametrize("bad_ttl", REJECTED_TTLS)
    def test_add_rejects_an_invalid_ttl(self, cache, bad_ttl):
        with pytest.raises(ConfigurationError):
            cache.add(CacheEntry(key="alpha", value="one"), ttl=bad_ttl)

    @pytest.mark.parametrize("bad_ttl", REJECTED_TTLS)
    def test_set_ttl_rejects_an_invalid_ttl(self, cache, bad_ttl):
        cache.add(CacheEntry(key="alpha", value="one"))

        with pytest.raises(ConfigurationError):
            cache.set_ttl(_key("alpha"), bad_ttl)

    @pytest.mark.parametrize("bad_ttl", REJECTED_TTLS)
    def test_set_ttl_rejects_an_invalid_ttl_even_when_the_key_is_absent(
        self, cache, bad_ttl
    ):
        # TTL validation must run whether or not the key exists: the `Cache`
        # service resolves the TTL before it calls the adapter, so an absent
        # key does not excuse a malformed TTL.
        with pytest.raises(ConfigurationError):
            cache.set_ttl(_key("does-not-exist"), bad_ttl)

    @pytest.mark.parametrize("ttl", [0, "nan", True])
    def test_a_rejected_ttl_writes_nothing(self, cache, ttl):
        with pytest.raises(ConfigurationError):
            cache.add(CacheEntry(key="1", value="a"), ttl=ttl)

        assert cache._adapter.count_matching("*") == 0


class TestTTLShapesAreAccepted:
    """A string, and specifically a string holding a float, is a valid TTL:
    env-substituted config (`TTL = "${CACHE_TTL|3600}"`) arrives as one.
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


class TestAnUnsetTTLUsesTheConfiguredTTL:
    @pytest.mark.parametrize("ttl", [None, ""])
    def test_add_with_an_unset_ttl_uses_the_configured_ttl(self, cache, ttl):
        cache.add(CacheEntry(key="1", value="a"), ttl=ttl)

        remaining = cache.get_ttl("cache_entry:::1")
        assert remaining is not None
        assert CONFIGURED_TTL - 10 <= remaining <= CONFIGURED_TTL

    @pytest.mark.parametrize("ttl", [None, ""])
    def test_set_ttl_with_an_unset_ttl_uses_the_configured_ttl(self, cache, ttl):
        cache.add(CacheEntry(key="1", value="a"), ttl=60)

        cache.set_ttl("cache_entry:::1", ttl)

        remaining = cache.get_ttl("cache_entry:::1")
        assert remaining is not None
        assert CONFIGURED_TTL - 10 <= remaining <= CONFIGURED_TTL
