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


class TestGetAllPaginationAgrees:
    def test_last_position_means_the_same_thing_on_every_adapter(self, cache, request):
        """A 5th cross-adapter divergence, found by running this suite.

        Memory treats `last_position` as a list offset into a freshly
        sorted-by-insertion key list (`results[last_position:last_position
        + size]` in `memory.py`), which also makes `size` a hard cap on the
        page length. Redis passes both straight through to `SCAN`
        (`self._client.scan(cursor=last_position, match=key_pattern,
        count=size)` in `redis.py`): `last_position` is an opaque cursor,
        not an offset, and `count` is only a hint Redis uses to decide how
        much internal work to do, not a page-size cap, so a single call can
        return more than `size` results. The continuation cursor `scan`
        returns for the next call is discarded by `get_all` entirely too.
        Not one of #1391/#1392/#1393/#1399 — filed as its own follow-up,
        #1401.

        The assertion below only pins the `size`-as-a-cap half of the
        divergence: it is guaranteed true on memory and, empirically,
        overwhelmingly likely to be violated by at least one call on Redis
        for a keyspace this size, regardless of Redis' per-server random
        hash seed. An earlier version asserted that walking
        `last_position=0, 1, 2, ...` visits every entry, but Redis' `SCAN`
        `COUNT` being a hint means a single call can happen to return every
        matching key, which would XPASS a `strict=True` xfail.
        """
        if request.node.callspec.params["cache"]["provider"] == "redis":
            request.applymarker(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "#1401: get_all's size means 'return at most this "
                        "many results' on memory but is only a hint to "
                        "Redis' SCAN about how much work to do per call, "
                        "so a single call can return more than size "
                        "results."
                    ),
                )
            )

        entries = [CacheEntry(key=f"k{i}", value=str(i)) for i in range(20)]
        for entry in entries:
            cache.add(entry)

        pages = [
            cache.get_all("cache_entry:::*", last_position=last_position, size=1)
            for last_position in range(30)
        ]

        assert all(len(page) <= 1 for page in pages)


class TestPatternLanguageIsAGlobOnEveryAdapter:
    def test_pattern_is_a_glob_on_every_adapter(self, cache, request):
        """A literal `.` is where glob and regex disagree.

        Redis' `SCAN ... MATCH` is a real glob, where `.` is an ordinary
        character. The memory cache compiles `key_pattern` straight into a
        Python regex, where `.` matches any character, so
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
