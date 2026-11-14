"""The cache Port members, and what the `Cache` service writes through them.

The service builds keys before it calls the adapter, so some of these tests
read the adapter directly to check what the service wrote.
"""

import logging
import math

import pytest

from protean.infra.cache import GET_ALL_MAX
from protean.port.cache import CacheCapabilities, CacheHealth

from .conftest import CacheEntry

KEY_VALUE = pytest.mark.requires(CacheCapabilities.KEY_VALUE)


@KEY_VALUE
class TestTheServiceWritesThroughThePort:
    def test_add_stores_the_projection_dict_under_its_key(self, cache):
        entry = CacheEntry(key="1", value="a")
        cache.add(entry)

        assert cache._adapter.get("cache_entry:::1") == {"key": "1", "value": "a"}
        assert cache.get("cache_entry:::1") == entry


@pytest.mark.requires(CacheCapabilities.KEY_VALUE, CacheCapabilities.PATTERN_MATCH)
class TestGetAllAtTheRealCap:
    def test_returns_the_first_entries_in_key_order_and_warns_once(self, cache, caplog):
        keys = [f"{i:05d}" for i in range(GET_ALL_MAX + 1)]
        # Insert in reverse so the result's order comes from the sort.
        for key in reversed(keys):
            cache.add(CacheEntry(key=key, value="v"))

        with caplog.at_level(logging.WARNING, logger="protean.infra.cache"):
            entries = cache._get_all("cache_entry:::*")

        assert [str(e.key) for e in entries] == keys[:GET_ALL_MAX]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "'cache_entry:::*'" in warnings[0].getMessage()
        assert str(GET_ALL_MAX + 1) in warnings[0].getMessage()


@KEY_VALUE
class TestTheAdapterPort:
    def test_put_then_get_round_trips_a_dict(self, adapter):
        adapter.put("k", {"a": 1, "b": "two"}, 60.0)

        assert adapter.get("k") == {"a": 1, "b": "two"}

    def test_put_replaces_the_earlier_value(self, adapter):
        adapter.put("k", {"a": 1}, 60.0)

        adapter.put("k", {"a": 2}, 60.0)

        assert adapter.get("k") == {"a": 2}

    def test_a_stored_entry_is_isolated_from_the_callers_dicts(self, adapter):
        value = {"a": {"b": 1}}
        adapter.put("k", value, 60.0)

        value["a"]["b"] = 2
        adapter.get("k")["a"]["b"] = 3

        assert adapter.get("k") == {"a": {"b": 1}}

    @pytest.mark.requires(CacheCapabilities.TTL)
    def test_put_without_a_ttl_never_expires(self, adapter):
        adapter.put("k", {"a": 1}, None)

        assert adapter.get_ttl("k") == math.inf

    def test_get_of_an_absent_key_returns_none(self, adapter):
        assert adapter.get("absent") is None

    def test_delete_removes_the_key(self, adapter):
        adapter.put("k", {"a": 1}, 60.0)

        adapter.delete("k")

        assert adapter.get("k") is None

    def test_delete_of_an_absent_key_does_nothing(self, adapter):
        adapter.put("k", {"a": 1}, 60.0)

        adapter.delete("absent")

        assert adapter.get("k") == {"a": 1}

    def test_clear_removes_every_entry(self, adapter):
        adapter.put("a", {"a": 1}, 60.0)
        adapter.put("b", {"b": 2}, 60.0)

        adapter.clear()

        assert (adapter.get("a"), adapter.get("b")) == (None, None)

    @pytest.mark.requires(CacheCapabilities.PATTERN_MATCH)
    def test_delete_matching_with_no_match_does_nothing(self, adapter):
        adapter.put("k", {"a": 1}, 60.0)

        adapter.delete_matching("absent:::*")

        assert adapter.keys_matching("*") == ["k"]

    @pytest.mark.requires(CacheCapabilities.TTL)
    def test_set_ttl_on_an_absent_key_creates_nothing(self, adapter):
        adapter.set_ttl("absent", 60.0)

        assert adapter.get("absent") is None
        assert adapter.get_ttl("absent") is None

    def test_ping_reports_the_cache_reachable(self, adapter):
        assert adapter.ping() is True

    def test_health_returns_a_cache_health_record(self, adapter):
        assert isinstance(adapter.health(), CacheHealth)

    def test_the_domain_hands_out_the_adapter_s_connection(self, test_domain, adapter):
        assert test_domain.caches.get_connection("default") is adapter.get_connection()
