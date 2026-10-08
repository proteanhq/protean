"""Core unit tests for RedisBroker._read_blocking_streams.

The override reads the pending lists of every stream in one XREADGROUP call,
then waits for a new message on all the streams in a second call. These tests
record every ``xreadgroup`` call on a hand-built client, so no Redis server is
needed. The live behaviour is covered in
tests/adapters/broker/redis/test_redis_read_blocking_streams.py.
"""

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker

pytestmark = pytest.mark.no_test_domain

STREAMS = ["orders", "orders:backfill"]


class _FakeRedisClient:
    """Stand-in for the redis-py client, recording XREADGROUP and XGROUP calls.

    ``responses`` is consumed one item per ``xreadgroup`` call. An item that is
    an exception instance is raised instead of returned.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple] = []

    def ping(self):
        return True

    def xgroup_create(self, stream, group_name, id=None, mkstream=False):
        self.calls.append(("xgroup_create", stream))
        return True

    def xreadgroup(self, group, consumer, streams, **kwargs):
        self.calls.append(("xreadgroup", list(streams.items()), kwargs))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def reads(self):
        return [call for call in self.calls if call[0] == "xreadgroup"]


def _broker(client):
    """Build a RedisBroker bypassing __init__ (no live connection needed)."""
    broker = object.__new__(RedisBroker)
    broker.redis_instance = client
    broker._created_groups_set = set()
    broker._group_creation_times = {}
    return broker


def _read(broker, timeout_ms, count=1):
    return broker._read_blocking_streams(
        STREAMS, "group", "consumer-1", timeout_ms=timeout_ms, count=count
    )


def _entry(identifier, n):
    return (identifier.encode(), {b"data": f'{{"n": {n}}}'.encode()})


EMPTY = {"orders": [], "orders:backfill": []}


class TestPendingRead:
    @pytest.mark.parametrize("timeout_ms", [0, 250, 5000])
    def test_pending_read_sends_both_streams_with_id_zero_and_no_block(
        self, timeout_ms
    ):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        assert _read(broker, timeout_ms, count=7) == EMPTY

        _, ids, kwargs = client.reads[0]
        assert ids == [("orders", "0"), ("orders:backfill", "0")]
        assert "block" not in kwargs
        assert kwargs["count"] == 7

    def test_pending_entries_are_returned_without_new_read(self):
        # The reply lists the backfill stream first; the result keeps the
        # requested order.
        pending = [
            [b"orders:backfill", [_entry("2-0", 2)]],
            [b"orders", [_entry("1-0", 1)]],
        ]
        client = _FakeRedisClient([pending])
        broker = _broker(client)

        result = _read(broker, 250)

        assert result == {
            "orders": [("1-0", {"n": 1})],
            "orders:backfill": [("2-0", {"n": 2})],
        }
        assert list(result) == STREAMS
        assert len(client.reads) == 1

    def test_pending_entries_without_fields_are_skipped(self):
        # A pending entry whose message was deleted comes back with no fields.
        client = _FakeRedisClient([[[b"orders", [(b"1-0", None)]]], []])
        broker = _broker(client)

        assert _read(broker, 0) == EMPTY
        assert len(client.reads) == 2


class TestNewMessageRead:
    @pytest.mark.parametrize(
        ("timeout_ms", "expected_block"),
        [(0, None), (250, 250), (1000, 1000), (5000, 1000)],
    )
    def test_one_new_message_read_with_capped_block(self, timeout_ms, expected_block):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        assert _read(broker, timeout_ms, count=7) == EMPTY

        assert len(client.reads) == 2
        _, ids, kwargs = client.reads[1]
        assert ids == [("orders", ">"), ("orders:backfill", ">")]
        assert kwargs["block"] == expected_block
        assert kwargs["count"] == 7

    def test_new_entries_are_grouped_by_stream(self):
        new = [[b"orders", [_entry("5-0", 5)]]]
        client = _FakeRedisClient([[], new])
        broker = _broker(client)

        result = _read(broker, 1000)

        assert result == {"orders": [("5-0", {"n": 5})], "orders:backfill": []}
        assert list(result) == STREAMS

    def test_reply_for_a_stream_not_requested_is_ignored(self):
        new = [[b"other", [_entry("7-0", 7)]], [b"orders", [_entry("8-0", 8)]]]
        client = _FakeRedisClient([[], new])
        broker = _broker(client)

        result = _read(broker, 0)

        assert result == {"orders": [("8-0", {"n": 8})], "orders:backfill": []}

    def test_groups_are_ensured_on_every_stream_before_reading(self):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        _read(broker, 0)

        assert client.calls[:2] == [
            ("xgroup_create", "orders"),
            ("xgroup_create", "orders:backfill"),
        ]


class TestErrors:
    def test_negative_timeout_is_logged_and_returns_empty(self, caplog):
        client = _FakeRedisClient([])
        broker = _broker(client)

        with caplog.at_level("ERROR", logger="protean.adapters.broker.redis"):
            assert _read(broker, -5) == EMPTY

        assert client.reads == []
        assert "broker.redis.read_blocking_failed" in caplog.text

    @pytest.mark.parametrize(
        ("timeout_ms", "expected_block"), [(0, None), (250, 250), (5000, 1000)]
    )
    def test_nogroup_recreates_groups_on_both_streams_and_retries_once(
        self, timeout_ms, expected_block
    ):
        retry = [[b"orders:backfill", [_entry("9-0", 9)]]]
        client = _FakeRedisClient(
            [[], redis.ResponseError("NOGROUP No such consumer group"), retry]
        )
        broker = _broker(client)

        result = _read(broker, timeout_ms, count=7)

        assert result == {"orders": [], "orders:backfill": [("9-0", {"n": 9})]}
        # Groups were created once up front, then again on both streams after
        # NOGROUP discarded the cache, before the single retry.
        names = [call[0] for call in client.calls]
        assert names == [
            "xgroup_create",
            "xgroup_create",
            "xreadgroup",
            "xreadgroup",
            "xgroup_create",
            "xgroup_create",
            "xreadgroup",
        ]
        assert [call[1] for call in client.calls[4:6]] == STREAMS
        _, ids, kwargs = client.reads[2]
        assert ids == [("orders", ">"), ("orders:backfill", ">")]
        assert kwargs["block"] == expected_block
        assert kwargs["count"] == 7

    def test_second_nogroup_returns_empty_without_looping(self, caplog):
        nogroup = redis.ResponseError("NOGROUP No such consumer group")
        client = _FakeRedisClient([[], nogroup, nogroup])
        broker = _broker(client)

        with caplog.at_level("ERROR", logger="protean.adapters.broker.redis"):
            assert _read(broker, 0) == EMPTY

        assert len(client.reads) == 3
        assert "broker.redis.nogroup_retry_failed" in caplog.text

    def test_other_response_error_is_logged_and_returns_empty(self, caplog):
        client = _FakeRedisClient([redis.ResponseError("WRONGTYPE")])
        broker = _broker(client)

        with caplog.at_level("ERROR", logger="protean.adapters.broker.redis"):
            assert _read(broker, 0) == EMPTY

        assert len(client.reads) == 1
        assert "broker.redis.read_blocking_failed" in caplog.text

    def test_connection_error_reconnects_and_returns_empty(self, caplog):
        client = _FakeRedisClient(
            [redis.ConnectionError("Connection closed by server")]
        )
        broker = _broker(client)
        reconnects = []
        broker._ensure_connection = lambda: reconnects.append(True) or True

        with caplog.at_level("ERROR", logger="protean.adapters.broker.redis"):
            assert _read(broker, 0) == EMPTY

        assert reconnects == [True]
        assert "broker.redis.read_blocking_failed" in caplog.text
