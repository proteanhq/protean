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
    """`get_all` paginates the same way on every adapter (#1401).

    Matching entries are ordered by key ascending; `last_position` is a
    zero-based offset into that order and `size` is a hard cap on the page.
    Memory used to page over insertion order and Redis forwarded
    `last_position`/`size` straight to `SCAN`, where the cursor is opaque and
    `count` is only a work hint, so the same offset returned different entries
    on the two adapters and `size` did not cap the Redis page.
    """

    COUNT = 20
    PATTERN = "cache_entry:::*"

    def _load(self, cache):
        for i in range(self.COUNT):
            cache.add(CacheEntry(key=f"k{i}", value=str(i)))

    def test_size_is_a_hard_cap(self, cache):
        self._load(cache)

        pages = [
            cache.get_all(self.PATTERN, last_position=n, size=1)
            for n in range(self.COUNT)
        ]

        # Every offset 0..COUNT-1 has an entry, so a size-1 page holds exactly
        # one: `== 1`, not `<= 1`, so an adapter that returned `[]` for every
        # call (which also satisfies `<= 1`) fails here, and one that ignored
        # `size` and returned the whole set fails too.
        assert len(pages) == self.COUNT
        assert all(len(page) == 1 for page in pages)

    def test_offsets_tile_the_result_set_in_one_stable_order(self, cache):
        self._load(cache)

        walked = []
        for n in range(self.COUNT):
            walked.extend(cache.get_all(self.PATTERN, last_position=n, size=1))

        single_page = cache.get_all(self.PATTERN, last_position=0, size=self.COUNT)

        # The order is keys sorted ascending, the same on every adapter. Pin the
        # concrete sequence, not just that the adapter agrees with itself: memory
        # used to page over insertion order (k0..k19), so without the sort this
        # would still tile the set but in the wrong order and disagree with
        # Redis. As strings, `k10` sorts before `k2`, so the order is not k0..k19.
        expected_order = sorted(f"k{i}" for i in range(self.COUNT))

        # Walking size-1 pages across every offset recovers every entry once, in
        # the same order a single page returns: no duplicate, no omission, so the
        # offset names the same entry either way.
        assert [entry.key for entry in walked] == expected_order
        assert [entry.key for entry in single_page] == expected_order

    def test_past_the_end_is_empty(self, cache):
        self._load(cache)

        assert cache.get_all(self.PATTERN, last_position=self.COUNT, size=5) == []
        assert cache.get_all(self.PATTERN, last_position=self.COUNT + 100, size=5) == []

    def test_multi_item_page_caps_at_size_and_at_the_end(self, cache):
        self._load(cache)

        assert len(cache.get_all(self.PATTERN, last_position=0, size=5)) == 5
        # Two entries left past offset 18, fewer than the size-5 request.
        assert len(cache.get_all(self.PATTERN, last_position=18, size=5)) == 2


class TestPatternLanguageIsAGlobOnEveryAdapter:
    def test_pattern_is_a_glob_on_every_adapter(self, cache):
        """A literal `.` is where glob and regex disagree.

        Redis' `SCAN ... MATCH` is a real glob, where `.` is an ordinary
        character. The memory cache matches `key_pattern` with `fnmatch`, a
        glob too, so a literal `.` matches only a literal `.` on both
        adapters.
        """
        literal_dot = CacheEntry(key="a.c", value="literal-dot")
        any_char = CacheEntry(key="abc", value="any-char")
        cache.add(literal_dot)
        cache.add(any_char)

        results = cache.get_all("cache_entry:::a.c")

        assert results == [literal_dot]

    def test_count_treats_the_pattern_as_a_glob(self, cache):
        """`count` reads `.` as a literal, the same as `get_all`.

        The shared `count` test uses `*`, which selects the same keys under
        a glob and under a regex, so it cannot tell the two apart. A literal
        `.` can: under a regex it would also count the `abc` entry.
        """
        cache.add(CacheEntry(key="a.c", value="literal-dot"))
        cache.add(CacheEntry(key="abc", value="any-char"))

        assert cache.count("cache_entry:::a.c") == 1

    def test_remove_by_key_pattern_treats_the_pattern_as_a_glob(self, cache):
        """`remove_by_key_pattern` reads `.` as a literal, the same as
        `get_all`.

        Under a regex the `.` would also match `abc`, so the removal would
        take both entries. Over-deletion on a truncate path is the dangerous
        direction, so pin it: only the literal-dot key is removed.
        """
        cache.add(CacheEntry(key="a.c", value="literal-dot"))
        cache.add(CacheEntry(key="abc", value="any-char"))

        cache.remove_by_key_pattern("cache_entry:::a.c")

        assert cache.get("cache_entry:::abc") is not None
        assert cache.get("cache_entry:::a.c") is None
