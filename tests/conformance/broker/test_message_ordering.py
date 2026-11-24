"""Brokers that declare ``MESSAGE_ORDERING`` return a stream's messages in
the order they were published."""

import pytest

from protean.port.broker import BrokerCapabilities

STREAM = "ordered_stream"
GROUP = "ordered_group"


@pytest.mark.requires(BrokerCapabilities.MESSAGE_ORDERING)
def test_one_read_returns_messages_in_publish_order(broker):
    identifiers = [broker.publish(STREAM, {"n": n}) for n in range(5)]

    messages = broker.read(STREAM, GROUP, 5)

    assert [identifier for identifier, _ in messages] == identifiers
    assert [message["n"] for _, message in messages] == [0, 1, 2, 3, 4]


@pytest.mark.requires(BrokerCapabilities.MESSAGE_ORDERING)
def test_successive_reads_continue_in_publish_order(broker):
    for n in range(6):
        broker.publish(STREAM, {"n": n})

    first = broker.read(STREAM, GROUP, 3)
    second = broker.read(STREAM, GROUP, 3)

    assert [message["n"] for _, message in first + second] == [0, 1, 2, 3, 4, 5]
