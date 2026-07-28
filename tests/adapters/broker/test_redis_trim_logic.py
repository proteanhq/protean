"""Core unit tests for RedisBroker.trim() branching and its id-parsing helpers.

trim() is also exercised end-to-end against a live Redis in
tests/adapters/broker/redis/test_redis_stream_retention.py (marked
``@pytest.mark.redis``, run only in the full matrix). These tests cover the pure
decision logic — which XTRIM form is chosen, and how ``"ms-seq"`` stream ids are
compared — without a running server, so the branching is verified in the core
suite too. The broker is built with ``object.__new__`` so no connection is made;
only ``redis_instance`` (the client the trim path reads through) is set.
"""

import redis

from protean.adapters.broker.redis import RedisBroker


class _FakeRedisClient:
    """Hand-built stand-in for the redis-py client, recording XTRIM calls.

    Only the two methods trim() reaches (``xinfo_groups`` and ``xtrim``) are
    implemented. ``xtrim`` records its keyword arguments so a test can assert
    which form (MINID vs MAXLEN) was used.
    """

    def __init__(
        self,
        *,
        groups_info=None,
        groups_error=False,
        trim_error=False,
        trimmed=0,
    ):
        self._groups_info = groups_info or []
        self._groups_error = groups_error
        self._trim_error = trim_error
        self._trimmed = trimmed
        self.xtrim_calls: list[dict] = []

    def xinfo_groups(self, stream):
        if self._groups_error:
            raise redis.ResponseError("no such key")
        return self._groups_info

    def xtrim(self, stream, *, minid=None, maxlen=None, approximate=None):
        self.xtrim_calls.append(
            {
                "stream": stream,
                "minid": minid,
                "maxlen": maxlen,
                "approximate": approximate,
            }
        )
        if self._trim_error:
            raise redis.ResponseError("trim failed")
        return self._trimmed


def _broker(client):
    """Build a RedisBroker bypassing __init__ (no live connection needed)."""
    broker = object.__new__(RedisBroker)
    broker.redis_instance = client
    return broker


def _group(last_delivered_id):
    return {"name": "g", "last-delivered-id": last_delivered_id}


class TestTrimBranching:
    """trim() picks XTRIM MINID for multiple groups, MAXLEN otherwise."""

    def test_missing_stream_returns_zero(self):
        """xinfo_groups raising ResponseError (no such stream) trims nothing."""
        client = _FakeRedisClient(groups_error=True)
        broker = _broker(client)

        assert broker.trim("orders", 100) == 0
        assert client.xtrim_calls == []

    def test_multi_group_trims_at_slowest_position(self):
        """Two groups -> MINID at the smallest last-delivered-id, not MAXLEN."""
        client = _FakeRedisClient(groups_info=[_group("9-0"), _group("5-0")], trimmed=7)
        broker = _broker(client)

        removed = broker.trim("orders", 100)

        assert removed == 7
        assert len(client.xtrim_calls) == 1
        call = client.xtrim_calls[0]
        assert call["minid"] == "5-0"
        assert call["maxlen"] is None
        assert call["approximate"] is True

    def test_single_group_uses_maxlen(self):
        """One group -> MAXLEN at the requested size, not MINID."""
        client = _FakeRedisClient(groups_info=[_group("42-0")])
        broker = _broker(client)

        broker.trim("orders", 100)

        call = client.xtrim_calls[0]
        assert call["maxlen"] == 100
        assert call["minid"] is None
        assert call["approximate"] is True

    def test_zero_groups_uses_maxlen(self):
        """No groups -> MAXLEN (a fixed cap is safe with no reader to outrun)."""
        client = _FakeRedisClient(groups_info=[])
        broker = _broker(client)

        broker.trim("orders", 100)

        assert client.xtrim_calls[0]["maxlen"] == 100
        assert client.xtrim_calls[0]["minid"] is None

    def test_single_group_non_positive_maxlen_trims_nothing(self):
        """maxlen <= 0 in the MAXLEN branch returns 0 and issues no xtrim.

        `xtrim(maxlen=0)` would empty the stream, so a non-positive cap is
        refused rather than treated as "delete everything".
        """
        for bad_maxlen in (0, -5):
            client = _FakeRedisClient(groups_info=[_group("42-0")])
            broker = _broker(client)

            assert broker.trim("orders", bad_maxlen) == 0
            assert client.xtrim_calls == []

    def test_multi_group_ignores_non_positive_maxlen(self):
        """maxlen <= 0 does not disable the MINID (multi-group) branch.

        The multi-group branch bounds by consumer progress, not maxlen, so it
        still trims by MINID even when maxlen is 0.
        """
        client = _FakeRedisClient(groups_info=[_group("9-0"), _group("5-0")], trimmed=3)
        broker = _broker(client)

        assert broker.trim("orders", 0) == 3
        assert client.xtrim_calls[0]["minid"] == "5-0"

    def test_trim_error_returns_zero(self):
        """A ResponseError from xtrim is swallowed and reported as 0 removed."""
        client = _FakeRedisClient(groups_info=[_group("42-0")], trim_error=True)
        broker = _broker(client)

        assert broker.trim("orders", 100) == 0

    def test_never_read_group_keeps_whole_stream(self):
        """Two groups where one never read ("0-0") -> MINID "0-0" removes nothing."""
        client = _FakeRedisClient(groups_info=[_group("0-0"), _group("9-0")])
        broker = _broker(client)

        broker.trim("orders", 100)

        assert client.xtrim_calls[0]["minid"] == "0-0"


class TestMinLastDeliveredId:
    """_min_last_delivered_id compares ids numerically and needs two groups."""

    def test_single_group_returns_none(self):
        """Fewer than two groups -> None (caller falls back to MAXLEN)."""
        broker = _broker(_FakeRedisClient())

        assert broker._min_last_delivered_id([_group("5-0")]) is None

    def test_compares_numerically_not_lexicographically(self):
        """ "100-0" must sort after "99-0" (string order would pick "100-0")."""
        broker = _broker(_FakeRedisClient())

        result = broker._min_last_delivered_id([_group("100-0"), _group("99-0")])

        assert result == "99-0"

    def test_returns_minimum_when_smallest_id_is_in_the_middle(self):
        """The minimum is picked regardless of position in the group list.

        With the smallest id neither first nor last, a "pick first" or "pick
        last" regression would return the wrong floor.
        """
        broker = _broker(_FakeRedisClient())

        result = broker._min_last_delivered_id(
            [_group("9-0"), _group("2-0"), _group("5-0")]
        )

        assert result == "2-0"

    def test_malformed_id_is_selected_as_minimum(self):
        """A malformed id sorts first ((-1, -1)), so it is chosen as the floor.

        Selecting it keeps the whole stream conservatively — against real Redis
        `xtrim(minid="bad")` raises ResponseError, which trim() catches and
        reports as 0 removed.
        """
        broker = _broker(_FakeRedisClient())

        result = broker._min_last_delivered_id([_group("bad"), _group("5-0")])

        assert result == "bad"

    def test_non_dict_group_entries_are_ignored(self):
        """Entries that are not dicts are skipped, not fatal."""
        broker = _broker(_FakeRedisClient())

        result = broker._min_last_delivered_id(
            [_group("5-0"), "not-a-dict", _group("2-0")]
        )

        assert result == "2-0"

    def test_group_without_last_delivered_id_is_skipped(self):
        """A group dict missing last-delivered-id contributes no floor."""
        broker = _broker(_FakeRedisClient())

        result = broker._min_last_delivered_id(
            [_group("5-0"), {"name": "no-id"}, _group("2-0")]
        )

        assert result == "2-0"


class TestStreamIdSortKey:
    """_stream_id_sort_key parses "ms-seq" into an (int, int) tuple."""

    def test_parses_ms_and_seq(self):
        assert RedisBroker._stream_id_sort_key("100-3") == (100, 3)

    def test_missing_seq_defaults_to_zero(self):
        assert RedisBroker._stream_id_sort_key("100") == (100, 0)

    def test_malformed_id_sorts_first(self):
        """A non-numeric id sorts first ((-1, -1)) so it never masks a real floor."""
        assert RedisBroker._stream_id_sort_key("not-anid") == (-1, -1)
