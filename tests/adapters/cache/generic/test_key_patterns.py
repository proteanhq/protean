"""Cross-adapter key-pattern behaviour for `get_all`/`count`/`remove_by_key_pattern`."""

from __future__ import annotations

import pytest

from .conftest import CacheEntry


class TestSharedPatternBehaviour:
    def test_get_all_returns_matching_entries(self, cache):
        alpha = CacheEntry(key="alpha", value="one")
        beta = CacheEntry(key="beta", value="two")
        cache.add(alpha)
        cache.add(beta)

        results = cache.get_all("cache_entry:::*")

        assert len(results) == 2
        assert alpha in results
        assert beta in results

    def test_count_counts_matching_entries(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        cache.add(CacheEntry(key="beta", value="two"))

        assert cache.count("cache_entry:::*") == 2

    def test_remove_by_key_pattern_removes_matching_entries(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))
        cache.add(CacheEntry(key="beta", value="two"))

        cache.remove_by_key_pattern("cache_entry:::*")

        assert cache.count("cache_entry:::*") == 0


class TestRemoveByKeyPatternOnNoMatch:
    def test_remove_by_key_pattern_is_silent_when_nothing_matches(self, cache, request):
        """A 4th cross-adapter divergence, found by running this suite.

        Memory's `remove_by_key_pattern` filters to an empty key list and
        loops zero times: silent. Redis' builds `values` from `scan_iter`
        and calls `self._client.delete(*values)`; when nothing matches that
        is `delete()` with zero keys, which raises
        `redis.exceptions.ResponseError: wrong number of arguments for 'del'
        command`. Not one of #1391/#1392/#1393 — filed as its own follow-up,
        #1399.
        """
        if request.node.callspec.params["cache"]["provider"] == "redis":
            request.applymarker(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "#1399: remove_by_key_pattern on a pattern that "
                        "matches nothing is silent on memory but raises "
                        "redis.exceptions.ResponseError on Redis, because "
                        "delete(*values) is called with zero keys."
                    ),
                )
            )

        cache.remove_by_key_pattern("cache_entry:::does-not-exist-*")


class TestPatternLanguageIsAGlobOnEveryAdapter:
    def test_pattern_is_a_glob_on_every_adapter(self, cache, request):
        """A literal `.` is where glob and regex disagree.

        Redis' `SCAN ... MATCH` is a real glob, where `.` is an ordinary
        character. The memory cache compiles `key_pattern` straight into a
        Python regex (`memory.py:168`), where `.` matches any character, so
        a pattern built on a literal dot also matches an entry that has a
        different character in that position.
        """
        if request.node.callspec.params["cache"]["provider"] == "memory":
            request.applymarker(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "#1393: a key pattern should be a glob on every "
                        "adapter. The memory cache compiles it as a regex, "
                        "so a literal '.' also matches any character."
                    ),
                )
            )

        literal_dot = CacheEntry(key="a.c", value="literal-dot")
        any_char = CacheEntry(key="abc", value="any-char")
        cache.add(literal_dot)
        cache.add(any_char)

        results = cache.get_all("cache_entry:::a.c")

        assert results == [literal_dot]
