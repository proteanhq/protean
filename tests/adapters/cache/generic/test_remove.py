"""Cross-adapter `remove_by_key` behaviour."""

from __future__ import annotations

from .conftest import CacheEntry


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


class TestRemoveByKey:
    def test_remove_by_key_removes_a_present_key(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        assert cache.get(_key("alpha")) is not None

        cache.remove_by_key(_key("alpha"))

        assert cache.get(_key("alpha")) is None

    def test_remove_by_key_is_silent_when_the_key_is_absent(self, cache):
        cache.remove_by_key(_key("does-not-exist"))
