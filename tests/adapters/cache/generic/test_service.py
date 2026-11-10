"""The `Cache` service and the cache Ports, on every configured adapter.

The service builds keys and resolves TTLs before it calls the adapter, so these
tests read the adapter directly to check what the service wrote.
"""

import logging
import math

import pytest

from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.infra.cache import GET_ALL_MAX
from tests.adapters.cache.generic.conftest import CACHE_CONFIGS, CacheEntry

CONFIGURED_TTL = 3600


@pytest.fixture(params=CACHE_CONFIGS)
def cache(request):
    """A cache configured with an hour-long `TTL`, far from `DEFAULT_TTL`."""
    domain = Domain(name="Test")
    domain.config["caches"]["default"] = {**request.param, "TTL": CONFIGURED_TTL}
    domain.register(CacheEntry)
    domain.init(traverse=False)

    with domain.domain_context():
        provider = domain.cache_for(CacheEntry)
        provider.clear()
        yield provider
        provider.clear()
        provider._close()


class TestTheServiceWritesThroughThePort:
    def test_add_stores_the_projection_dict_under_its_key(self, cache):
        entry = CacheEntry(key="1", value="a")
        cache.add(entry)

        assert cache._adapter.get("cache_entry:::1") == {"key": "1", "value": "a"}
        assert cache.get("cache_entry:::1") == entry

    @pytest.mark.parametrize("ttl", [None, ""])
    def test_an_unset_ttl_uses_the_configured_ttl(self, cache, ttl):
        cache.add(CacheEntry(key="1", value="a"), ttl=ttl)

        remaining = cache.get_ttl("cache_entry:::1")
        assert remaining is not None
        assert CONFIGURED_TTL - 10 <= remaining <= CONFIGURED_TTL

    @pytest.mark.parametrize("ttl", [0, "nan", True])
    def test_a_rejected_ttl_writes_nothing(self, cache, ttl):
        with pytest.raises(ConfigurationError):
            cache.add(CacheEntry(key="1", value="a"), ttl=ttl)

        assert cache._adapter.count_matching("*") == 0


class TestGetAllAtTheRealCap:
    def test_returns_the_first_entries_in_key_order_and_warns_once(self, cache, caplog):
        keys = [f"{i:05d}" for i in range(GET_ALL_MAX + 1)]
        for key in keys:
            cache.add(CacheEntry(key=key, value="v"))

        with caplog.at_level(logging.WARNING, logger="protean.infra.cache"):
            entries = cache._get_all("cache_entry:::*")

        assert [str(e.key) for e in entries] == keys[:GET_ALL_MAX]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "'cache_entry:::*'" in warnings[0].getMessage()
        assert str(GET_ALL_MAX + 1) in warnings[0].getMessage()


class TestTheAdapterPort:
    def test_put_then_get_round_trips_a_dict(self, cache):
        adapter = cache._adapter
        adapter.put("k", {"a": 1, "b": "two"}, 60.0)

        assert adapter.get("k") == {"a": 1, "b": "two"}

    def test_put_without_a_ttl_never_expires(self, cache):
        adapter = cache._adapter
        adapter.put("k", {"a": 1}, None)

        assert adapter.get_ttl("k") == math.inf

    def test_get_of_an_absent_key_returns_none(self, cache):
        assert cache._adapter.get("absent") is None

    def test_delete_of_an_absent_key_does_nothing(self, cache):
        adapter = cache._adapter
        adapter.put("k", {"a": 1}, 60.0)

        adapter.delete("absent")

        assert adapter.get("k") == {"a": 1}

    def test_delete_matching_with_no_match_does_nothing(self, cache):
        adapter = cache._adapter
        adapter.put("k", {"a": 1}, 60.0)

        adapter.delete_matching("absent:::*")

        assert adapter.keys_matching("*") == ["k"]

    def test_set_ttl_on_an_absent_key_creates_nothing(self, cache):
        adapter = cache._adapter

        adapter.set_ttl("absent", 60.0)

        assert adapter.get("absent") is None
        assert adapter.get_ttl("absent") is None

    def test_health_reports_no_pool_counters(self, cache):
        assert cache._adapter.health().pool is None
