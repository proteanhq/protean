"""Core unit tests for how RedisBroker._read_blocking maps ``timeout_ms`` to BLOCK.

Redis reads ``XREADGROUP ... BLOCK 0`` as "wait forever", and redis-py sends
BLOCK only when ``block`` is not None. So a zero timeout must reach the client
as ``block=None``, and the pending read (id ``"0"``) must never pass
``block=0``. These tests record the keyword arguments of every ``xreadgroup``
call on a hand-built client, so no Redis server is needed. The live behaviour
is covered in tests/adapters/broker/redis/test_redis_read_blocking_zero_timeout.py.
"""

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker


class _FakeRedisClient:
    """Stand-in for the redis-py client, recording XREADGROUP calls.

    ``responses`` is consumed one item per ``xreadgroup`` call. An item that is
    an exception instance is raised instead of returned.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.xreadgroup_calls: list[dict] = []
        self.xgroup_create_calls = 0

    def xgroup_create(self, stream, group_name, id=None, mkstream=False):
        self.xgroup_create_calls += 1
        return True

    def xreadgroup(self, group, consumer, streams, **kwargs):
        self.xreadgroup_calls.append(
            {"stream_id": next(iter(streams.values())), "kwargs": kwargs}
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _broker(client):
    """Build a RedisBroker bypassing __init__ (no live connection needed)."""
    broker = object.__new__(RedisBroker)
    broker.redis_instance = client
    broker._created_groups_set = set()
    broker._group_creation_times = {}
    return broker


def _read(broker, timeout_ms):
    return broker._read_blocking(
        "orders", "group", "consumer-1", timeout_ms=timeout_ms, count=1
    )


def _new_message_call(client):
    calls = [c for c in client.xreadgroup_calls if c["stream_id"] == ">"]
    assert len(calls) == 1
    return calls[0]


class TestBlockArgument:
    def test_zero_timeout_sends_no_block_on_new_read(self):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        assert _read(broker, 0) == []

        assert [c["stream_id"] for c in client.xreadgroup_calls] == ["0", ">"]
        assert _new_message_call(client)["kwargs"].get("block") is None

    def test_negative_timeout_sends_no_block_on_new_read(self):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        assert _read(broker, -5) == []

        assert _new_message_call(client)["kwargs"].get("block") is None

    @pytest.mark.parametrize(
        ("timeout_ms", "expected_block"),
        [(1, 1), (250, 250), (1000, 1000), (5000, 1000)],
    )
    def test_positive_timeout_is_passed_and_capped(self, timeout_ms, expected_block):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        assert _read(broker, timeout_ms) == []

        assert _new_message_call(client)["kwargs"].get("block") == expected_block

    @pytest.mark.parametrize("timeout_ms", [0, 250, 5000])
    def test_pending_read_never_blocks(self, timeout_ms):
        client = _FakeRedisClient([[], []])
        broker = _broker(client)

        _read(broker, timeout_ms)

        pending = [c for c in client.xreadgroup_calls if c["stream_id"] == "0"]
        assert len(pending) == 1
        assert pending[0]["kwargs"].get("block") is None

    def test_pending_message_is_returned_without_new_read(self):
        pending_response = [["orders", [(b"1-0", {b"data": b'{"n": 1}'})]]]
        client = _FakeRedisClient([pending_response])
        broker = _broker(client)

        assert _read(broker, 0) == [("1-0", {"n": 1})]
        assert [c["stream_id"] for c in client.xreadgroup_calls] == ["0"]


class TestNogroupRetryBlockArgument:
    """The NOGROUP retry uses the same block value as the normal new-message read."""

    @pytest.mark.parametrize(
        ("timeout_ms", "expected_block"), [(0, None), (250, 250), (5000, 1000)]
    )
    def test_retry_uses_same_block_value(self, timeout_ms, expected_block):
        client = _FakeRedisClient(
            [[], redis.ResponseError("NOGROUP No such consumer group"), []]
        )
        broker = _broker(client)

        assert _read(broker, timeout_ms) == []

        new_reads = [c for c in client.xreadgroup_calls if c["stream_id"] == ">"]
        assert len(new_reads) == 2
        assert all(c["kwargs"].get("block") == expected_block for c in new_reads)
        # The group was recreated after NOGROUP discarded the cache entry
        assert client.xgroup_create_calls == 2
