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
        + size]` in `memory.py`). Redis passes it straight through as an
        opaque `SCAN` cursor (`self._client.scan(cursor=last_position, ...)`
        in `redis.py`), where `count` is only a hint and the continuation
        cursor `get_all` should return for the next call is discarded. A
        caller that walks pages with `last_position` counting 0, 1, 2, ...
        (the only option `get_all` leaves it, since it never hands back a
        cursor to resume from) visits every entry exactly once on memory
        and an adapter-dependent, incomplete subset on Redis. Not one of
        #1391/#1392/#1393/#1399 — filed as its own follow-up, #1401.
        """
        if request.node.callspec.params["cache"]["provider"] == "redis":
            request.applymarker(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "#1401: get_all's last_position means 'skip this "
                        "many results' on memory but is an opaque Redis "
                        "SCAN cursor, so walking last_position=0,1,2,... "
                        "does not visit every entry on Redis."
                    ),
                )
            )

        entries = [CacheEntry(key=f"k{i}", value=str(i)) for i in range(20)]
        for entry in entries:
            cache.add(entry)

        seen = set()
        for last_position in range(30):
            page = cache.get_all("cache_entry:::*", last_position=last_position, size=1)
            seen.update(result.key for result in page)

        assert seen == {entry.key for entry in entries}


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
