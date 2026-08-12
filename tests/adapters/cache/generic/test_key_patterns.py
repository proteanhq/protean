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
    def test_remove_by_key_pattern_is_silent_when_nothing_matches(self, cache):
        """`remove_by_key_pattern` on a pattern that matches nothing is a
        no-op on every adapter.

        Memory's `remove_by_key_pattern` filters to an empty key list and
        loops zero times: silent. Redis builds `values` from `scan_iter`
        and only calls `self._client.delete(*values)` when `values` is
        non-empty; calling `delete()` with zero keys raises
        `redis.exceptions.ResponseError: wrong number of arguments for
        'del' command`.
        """
        cache.remove_by_key_pattern("cache_entry:::does-not-exist-*")

    def test_remove_by_key_pattern_on_no_match_leaves_other_keys_intact(self, cache):
        cache.add(CacheEntry(key="alpha", value="one"))

        cache.remove_by_key_pattern("cache_entry:::does-not-exist-*")

        assert cache.count("cache_entry:::*") == 1


class TestGetAllPaginationAgrees:
    def test_last_position_means_the_same_thing_on_every_adapter(
        self, cache, request, monkeypatch
    ):
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
        divergence. It is guaranteed true on memory as-is. On Redis, `scan`
        is stubbed to always answer with more keys than `size`, so the
        violation is deterministic instead of depending on `COUNT` being a
        hint that Redis happens to overshoot for this keyspace and the
        server's hash seed.
        """
        entries = [CacheEntry(key=f"k{i}", value=str(i)) for i in range(20)]
        for entry in entries:
            cache.add(entry)

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
            oversized_batch = [
                f"cache_entry:::{entries[0].key}",
                f"cache_entry:::{entries[1].key}",
            ]
            monkeypatch.setattr(
                cache.get_connection(),
                "scan",
                lambda cursor=0, match=None, count=None: (0, oversized_batch),
            )

        pages = [
            cache.get_all("cache_entry:::*", last_position=last_position, size=1)
            for last_position in range(30)
        ]

        assert all(len(page) <= 1 for page in pages)


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
