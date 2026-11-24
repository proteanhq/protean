"""Brokers that declare ``STREAM_RETENTION`` trim acknowledged entries and
never an entry a consumer group still needs."""

import pytest

from protean.port.broker import BrokerCapabilities

pytestmark = pytest.mark.requires(BrokerCapabilities.STREAM_RETENTION)

STREAM = "retained_stream"


def test_trim_keeps_every_entry_a_group_has_not_acknowledged(broker):
    # Enough entries that a broker which trims in blocks has a block to remove.
    total = 300
    for n in range(total):
        broker.publish(STREAM, {"n": n})
    acked = broker.read(STREAM, "fast", total)
    for identifier, _ in acked:
        broker.ack(STREAM, identifier, "fast")
    slow = broker.read(STREAM, "slow", 100)
    for identifier, _ in slow:
        broker.ack(STREAM, identifier, "slow")

    removed = broker._trim(STREAM)

    assert 0 <= removed <= 100
    remaining = broker.read(STREAM, "slow", total)
    assert sorted(message["n"] for _, message in remaining) == list(range(100, total))


def test_trim_of_a_missing_stream_removes_nothing(broker):
    assert broker._trim("missing_stream") == 0
