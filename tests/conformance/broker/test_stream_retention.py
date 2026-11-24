"""Brokers that declare ``STREAM_RETENTION`` trim acknowledged entries and
never an entry a consumer group still needs."""

import pytest

from protean.port.broker import BrokerCapabilities

pytestmark = pytest.mark.requires(BrokerCapabilities.STREAM_RETENTION)

STREAM = "retained_stream"

# Enough entries that a broker which trims in blocks has a block to remove.
TOTAL = 300


def _publish_all(broker):
    for n in range(TOTAL):
        broker.publish(STREAM, {"n": n})


def _read_and_ack(broker, group, limit, ack_limit):
    """Read ``limit`` entries for ``group`` and acknowledge the first ``ack_limit``."""
    entries = broker.read(STREAM, group, limit)
    assert len(entries) == limit
    for identifier, _ in entries[:ack_limit]:
        broker.ack(STREAM, identifier, group)


def test_trim_keeps_every_entry_a_group_has_not_read(broker):
    _publish_all(broker)
    _read_and_ack(broker, "fast", TOTAL, TOTAL)
    _read_and_ack(broker, "slow", 100, 100)

    removed = broker._trim(STREAM)

    assert 0 <= removed <= 100
    remaining = broker.read(STREAM, "slow", TOTAL)
    assert sorted(message["n"] for _, message in remaining) == list(range(100, TOTAL))


def test_trim_keeps_every_entry_a_group_has_read_and_not_acknowledged(broker):
    _publish_all(broker)
    _read_and_ack(broker, "fast", TOTAL, TOTAL)
    # Entries 50 to 199 are delivered to "slow" and stay pending, so a broker
    # that trims up to the last delivered entry has a whole block to remove.
    _read_and_ack(broker, "slow", 200, 50)

    removed = broker._trim(STREAM)

    assert 0 <= removed <= 50
    # A read without ``new_messages`` returns the new entries and then the
    # group's pending ones.
    remaining = broker.read(STREAM, "slow", TOTAL)
    assert sorted(message["n"] for _, message in remaining) == list(range(50, TOTAL))


def test_trim_removes_entries_every_group_has_acknowledged(broker):
    _publish_all(broker)
    _read_and_ack(broker, "fast", TOTAL, TOTAL)
    _read_and_ack(broker, "slow", TOTAL, TOTAL)

    assert broker._trim(STREAM) > 0


def test_trim_of_a_missing_stream_removes_nothing(broker):
    assert broker._trim("missing_stream") == 0
