"""Tests for trimming a Redis stream by consumer progress (XTRIM MINID).

``RedisBroker.trim`` removes only entries that every consumer group has read
and acknowledged. Each group's bound is its oldest pending entry when it has
pending entries, else its ``last-delivered-id``; the stream is trimmed at the
smallest bound. The trim is approximate (``~``), so Redis removes whole
macro-nodes of up to 100 entries and the stream can stay a little above the
bound. The tests publish 1,000 entries so a whole node falls below the bound.
"""

import json

import pytest

from protean.adapters.broker.redis import DATA_FIELD, RedisBroker
from tests.shared import REDIS_URI

STREAM = "orders"
TOTAL = 1000


def _broker(test_domain) -> RedisBroker:
    broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
    broker.clear()
    return broker


def _publish(broker: RedisBroker, count: int = TOTAL) -> list[str]:
    return [broker.publish(STREAM, {"n": i}) for i in range(count)]


def _read(broker: RedisBroker, group: str, count: int) -> list[str]:
    """XREADGROUP ``count`` new entries for ``group`` and return their ids."""
    response = broker._client.xreadgroup(
        group, f"{group}-c", {STREAM: ">"}, count=count
    )
    return [
        broker._decode_if_bytes(message_id)
        for _stream, messages in response or []
        for message_id, _fields in messages
    ]


def _read_and_ack(broker: RedisBroker, group: str, count: int) -> list[str]:
    ids = _read(broker, group, count)
    broker._client.xack(STREAM, group, *ids)
    return ids


def _remaining_ids(broker: RedisBroker) -> list[str]:
    return [
        broker._decode_if_bytes(message_id)
        for message_id, _fields in broker._client.xrange(STREAM)
    ]


@pytest.mark.redis
class TestTrimByConsumerProgress:
    def test_single_group_keeps_every_unread_entry(self, test_domain):
        broker = _broker(test_domain)
        ids = _publish(broker)
        broker.create_group(STREAM, "solo")
        assert _read_and_ack(broker, "solo", 10) == ids[:10]

        broker.trim(STREAM)

        remaining = _remaining_ids(broker)
        assert remaining[-(TOTAL - 10) :] == ids[10:]

    def test_two_groups_keep_entries_from_the_slower_groups_position(self, test_domain):
        broker = _broker(test_domain)
        ids = _publish(broker)
        broker.create_group(STREAM, "groupA")
        broker.create_group(STREAM, "groupB")
        assert _read_and_ack(broker, "groupA", 500) == ids[:500]
        assert _read_and_ack(broker, "groupB", 200) == ids[:200]

        removed = broker.trim(STREAM)

        remaining = _remaining_ids(broker)
        # B's last-delivered id is ids[199]; MINID keeps it and everything after.
        assert removed > 0
        assert remaining[-(TOTAL - 199) :] == ids[199:]
        assert ids[0] not in remaining
        assert len(remaining) == TOTAL - removed

    def test_oldest_pending_entry_survives_and_can_be_claimed(self, test_domain):
        broker = _broker(test_domain)
        ids = _publish(broker)
        broker.create_group(STREAM, "g")
        # The group reads every entry and acknowledges all but ids[500], so its
        # last-delivered id (ids[999]) is far above its oldest pending entry.
        assert _read(broker, "g", TOTAL) == ids
        broker._client.xack(STREAM, "g", *ids[:500], *ids[501:])

        removed = broker.trim(STREAM)

        remaining = _remaining_ids(broker)
        assert removed > 0
        assert ids[0] not in remaining
        assert remaining[-(TOTAL - 500) :] == ids[500:]
        claimed = broker._client.xclaim(STREAM, "g", "other-c", 0, [ids[500]])
        assert len(claimed) == 1
        claimed_id, fields = claimed[0]
        assert broker._decode_if_bytes(claimed_id) == ids[500]
        assert json.loads(fields[DATA_FIELD.encode()]) == {"n": 500}

    def test_pending_bound_wins_over_a_fully_acked_group(self, test_domain):
        broker = _broker(test_domain)
        ids = _publish(broker)
        broker.create_group(STREAM, "done")
        broker.create_group(STREAM, "busy")
        assert _read_and_ack(broker, "done", TOTAL) == ids
        assert _read(broker, "busy", 600) == ids[:600]
        broker._client.xack(STREAM, "busy", *ids[:300], *ids[301:600])

        broker.trim(STREAM)

        remaining = _remaining_ids(broker)
        assert ids[0] not in remaining
        assert remaining[-(TOTAL - 300) :] == ids[300:]

    def test_never_read_group_blocks_the_trim(self, test_domain):
        broker = _broker(test_domain)
        _publish(broker)
        broker.create_group(STREAM, "reader")
        broker.create_group(STREAM, "idle")
        _read_and_ack(broker, "reader", TOTAL)

        assert broker.trim(STREAM) == 0
        assert broker._client.xlen(STREAM) == TOTAL

    def test_stream_without_a_group_is_not_trimmed(self, test_domain):
        broker = _broker(test_domain)
        _publish(broker)

        assert broker.trim(STREAM) == 0
        assert broker._client.xlen(STREAM) == TOTAL

    def test_missing_stream_returns_zero(self, test_domain):
        broker = _broker(test_domain)

        assert broker.trim("no-such-stream") == 0

    def test_key_of_another_type_logs_the_error(self, test_domain, caplog):
        broker = _broker(test_domain)
        broker._client.set(STREAM, "not a stream")

        assert broker.trim(STREAM) == 0
        assert f"Failed to trim stream {STREAM}" in caplog.text
        assert "WRONGTYPE" in caplog.text

    def test_ids_above_2_pow_53_compare_exactly(self, test_domain):
        # Both millisecond parts round to 2**53 as Lua numbers. Compared that
        # way, group B's bound looks lower than group A's pending entry and the
        # trim removes the entry group A has not acknowledged.
        broker = _broker(test_domain)
        low, high = 2**53, 2**53 + 1
        ids = [
            broker._client.xadd(STREAM, {"n": seq}, id=f"{ms}-{seq}").decode()
            for ms in (low, high)
            for seq in range(200)
        ]
        broker.create_group(STREAM, "groupA")
        broker.create_group(STREAM, "groupB")
        assert _read(broker, "groupA", 6) == ids[:6]
        broker._client.xack(STREAM, "groupA", *ids[:5])
        assert _read_and_ack(broker, "groupB", 201) == ids[:201]

        assert broker.trim(STREAM) == 0
        assert _remaining_ids(broker) == ids
