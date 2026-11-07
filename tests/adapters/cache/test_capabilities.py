"""What each cache adapter declares through `CacheCapabilities`.

The conformance suite gates its tests on these flags, so a tier that gains or
loses a flag, or an adapter that declares the wrong tier, changes which tests
run against it.
"""

from typing import Any

import pytest

from protean.domain import Domain
from protean.port.cache import BaseCache, CacheCapabilities
from tests.shared import REDIS_URI

# The Redis test reads a property and writes no keys, so sharing a DB number
# with another suite cannot collide. This is the generic cache suite's number.
REDIS_DB = 6


def _cache_for(config: dict[str, Any]) -> BaseCache:
    domain = Domain(name="Test")
    domain.config["caches"]["default"] = config
    domain.init(traverse=False)
    return domain.caches["default"]


class TestTiers:
    def test_local_is_key_value_ttl_and_pattern_match(self):
        assert CacheCapabilities.LOCAL == (
            CacheCapabilities.KEY_VALUE
            | CacheCapabilities.TTL
            | CacheCapabilities.PATTERN_MATCH
        )

    def test_distributed_is_local_shared_and_durable(self):
        assert CacheCapabilities.DISTRIBUTED == (
            CacheCapabilities.LOCAL
            | CacheCapabilities.SHARED
            | CacheCapabilities.DURABLE
        )

    def test_local_is_a_subset_of_distributed(self):
        assert CacheCapabilities.LOCAL in CacheCapabilities.DISTRIBUTED
        assert CacheCapabilities.DISTRIBUTED not in CacheCapabilities.LOCAL

    @pytest.mark.parametrize(
        "flag", [CacheCapabilities.SHARED, CacheCapabilities.DURABLE]
    )
    def test_local_promises_nothing_across_instances(self, flag):
        assert flag not in CacheCapabilities.LOCAL


@pytest.mark.no_test_domain
class TestAdapterDeclarations:
    def test_memory_cache_declares_local(self):
        cache = _cache_for({"provider": "memory"})
        assert cache.capabilities == CacheCapabilities.LOCAL

    @pytest.mark.redis
    def test_redis_cache_declares_distributed(self):
        cache = _cache_for({"provider": "redis", "URI": f"{REDIS_URI}/{REDIS_DB}"})
        try:
            assert cache.capabilities == CacheCapabilities.DISTRIBUTED
        finally:
            cache.close()


def _stub_cache(*, with_capabilities: bool) -> type[BaseCache]:
    """A `BaseCache` subclass that implements every abstract member, except
    `capabilities` when `with_capabilities` is false.

    The member set comes from `BaseCache.__abstractmethods__`, so a member
    added to the port later cannot make the missing-`capabilities` case fail
    for the wrong reason.
    """
    members: dict[str, Any] = {
        name: (lambda self, *args, **kwargs: None)
        for name in BaseCache.__abstractmethods__
        if name != "capabilities"
    }
    if with_capabilities:
        members["capabilities"] = property(lambda self: CacheCapabilities.LOCAL)
    return type("StubCache", (BaseCache,), members)


class TestCapabilitiesIsRequired:
    def test_an_adapter_without_capabilities_cannot_be_built(self):
        assert "capabilities" in BaseCache.__abstractmethods__
        with pytest.raises(TypeError, match="capabilities"):
            _stub_cache(with_capabilities=False)("stub", None, {})

    def test_an_adapter_with_capabilities_can_be_built(self):
        cache = _stub_cache(with_capabilities=True)("stub", None, {})
        assert cache.capabilities == CacheCapabilities.LOCAL
