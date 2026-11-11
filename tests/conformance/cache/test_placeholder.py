"""A one-test placeholder that the cache port's conformance suite replaces."""

from protean.port.cache import CacheCapabilities


def test_the_adapter_declares_cache_capabilities(adapter):
    assert isinstance(adapter.capabilities, CacheCapabilities)
