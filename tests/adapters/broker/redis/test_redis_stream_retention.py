"""Tests for progress-safe stream retention (XTRIM) on the Redis broker.

``RedisBroker.trim`` caps a subscription's stream without dropping anything a
consumer group still needs:

- With more than one consumer group it trims by MINID at the slowest group's
  ``last-delivered-id``, so an entry a slow group has not read is never removed.
- With zero or one group it trims by MAXLEN, since there is at most one reader
  whose progress could be outrun.

Both use ``approximate=True``, so the stream may settle slightly above the
target but never below it.
"""

import pytest

from protean.adapters.broker.redis import RedisBroker
from tests.shared import REDIS_URI


def _broker(test_domain) -> RedisBroker:
    broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
    broker._client.flushdb()  # clean slate — flush only DB 0, not all Redis databases
    broker._created_groups_set.clear()
    broker._group_creation_times.clear()
    return broker


def _read_group(broker: RedisBroker, group: str, stream: str, count: int) -> list[str]:
    """XREADGROUP new messages for *group* and return their decoded ids."""
    response = broker._client.xreadgroup(
        group, f"{group}-c", {stream: ">"}, count=count
    )
    ids: list[str] = []
    for _stream_name, messages in response or []:
        for message_id, _fields in messages:
            ids.append(broker._decode_if_bytes(message_id))
    return ids


@pytest.mark.redis
class TestRedisStreamRetention:
    def test_multi_group_keeps_entries_the_slow_group_has_not_read(self, test_domain):
        """AC1: a slow consumer group keeps every entry it has not yet delivered.

        Group A drains the whole stream; group B reads only the first three.
        A MINID trim at group B's position must leave every unread entry (4..10)
        in place so group B can still read them.
        """
        broker = _broker(test_domain)
        stream = "orders"

        ids = [broker.publish(stream, {"n": i}) for i in range(10)]

        broker._ensure_group("groupA", stream)
        broker._ensure_group("groupB", stream)

        # Group A consumes everything; group B only the first three.
        assert _read_group(broker, "groupA", stream, 10) == ids
        assert _read_group(broker, "groupB", stream, 3) == ids[:3]

        # maxlen=1 would obliterate the stream under a plain MAXLEN trim, but the
        # multi-group branch ignores it and trims by the slow group's position.
        removed = broker.trim(stream, 1)
        assert isinstance(removed, int)

        # Group B can still read every entry it had not yet delivered.
        assert _read_group(broker, "groupB", stream, 100) == ids[3:]

    def test_never_read_group_keeps_whole_stream(self, test_domain):
        """A group parked at ``0-0`` (never read) makes MINID keep everything.

        With two groups both at ``last-delivered-id == 0-0``, the minimum floor
        is ``0-0``; no real entry is below it, so nothing is trimmed.
        """
        broker = _broker(test_domain)
        stream = "orders"

        broker._ensure_group("groupA", stream)
        broker._ensure_group("groupB", stream)
        for i in range(10):
            broker.publish(stream, {"n": i})

        removed = broker.trim(stream, 1)

        assert removed == 0
        assert broker._client.xlen(stream) == 10

    def test_single_group_bounds_stream_by_maxlen(self, test_domain):
        """AC2: with a single group, MAXLEN caps the stream near the target.

        Approximate trimming keeps at least ``maxlen`` entries and settles near
        it (whole macro-nodes at a time), well below the published total.
        """
        broker = _broker(test_domain)
        stream = "orders"

        published = 1000
        maxlen = 100
        for i in range(published):
            broker.publish(stream, {"n": i})
        broker._ensure_group("solo", stream)

        removed = broker.trim(stream, maxlen)
        xlen = broker._client.xlen(stream)

        assert isinstance(removed, int)
        assert removed > 0  # trimming actually removed entries
        assert xlen < published  # the stream is bounded below the total
        assert xlen >= maxlen  # approximate never drops below the cap
        assert xlen <= maxlen * 3  # settled near the cap (macro-node slack)

    def test_zero_group_stream_is_trimmed_by_maxlen(self, test_domain):
        """A stream with no consumer group still trims by MAXLEN."""
        broker = _broker(test_domain)
        stream = "orders"

        published = 1000
        maxlen = 100
        for i in range(published):
            broker.publish(stream, {"n": i})

        removed = broker.trim(stream, maxlen)
        xlen = broker._client.xlen(stream)

        assert removed > 0
        assert maxlen <= xlen < published

    def test_trim_missing_stream_returns_zero(self, test_domain):
        """Trimming a stream that does not exist is a no-op, not an error."""
        broker = _broker(test_domain)

        assert broker.trim("no-such-stream", 100) == 0
