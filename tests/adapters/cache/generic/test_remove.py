"""Cross-adapter `remove_by_key` behaviour."""

from __future__ import annotations

import pytest

from protean.adapters.cache.memory import MemoryCache

from .conftest import CacheEntry


def _key(identifier: str) -> str:
    return f"cache_entry:::{identifier}"


class TestRemoveByKey:
    def test_remove_by_key_removes_a_present_key(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        assert cache.get(_key("alpha")) is not None

        cache.remove_by_key(_key("alpha"))

        assert cache.get(_key("alpha")) is None

    def test_remove_by_key_is_silent_when_the_key_is_absent(self, cache, request):
        if isinstance(cache, MemoryCache):
            request.applymarker(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "#1391: removing an absent key should do nothing. "
                        "The memory cache raises KeyError; Redis is already "
                        "silent."
                    ),
                )
            )

        cache.remove_by_key(_key("does-not-exist"))
