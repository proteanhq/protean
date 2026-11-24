"""Brokers that declare ``BLOCKING_READ`` wait for a message to arrive."""

import threading
import time

import pytest

from protean.port.broker import BrokerCapabilities

STREAM = "blocking_stream"
GROUP = "blocking_group"
CONSUMER = "blocking_consumer"

# The longest wait a broker must honour. The Redis broker caps a blocking read
# at one second.
TIMEOUT_MS = 1000


@pytest.mark.requires(BrokerCapabilities.BLOCKING_READ)
def test_a_read_waits_for_a_message_published_while_it_waits(broker):
    # Join the group first, so the message published later is new to it.
    assert broker.read_blocking(STREAM, GROUP, CONSUMER, timeout_ms=0) == []

    publisher = threading.Timer(0.1, broker.publish, (STREAM, {"n": 1}))
    publisher.start()
    started = time.monotonic()
    try:
        messages = broker.read_blocking(STREAM, GROUP, CONSUMER, timeout_ms=TIMEOUT_MS)
        elapsed = time.monotonic() - started
    finally:
        publisher.join()

    assert [message for _, message in messages] == [{"n": 1}]
    # The publish ends the wait, before the timeout runs out.
    assert elapsed < TIMEOUT_MS / 1000


@pytest.mark.requires(BrokerCapabilities.BLOCKING_READ)
def test_a_read_returns_at_once_when_a_message_is_waiting(broker):
    assert broker.read_blocking(STREAM, GROUP, CONSUMER, timeout_ms=0) == []
    identifier = broker.publish(STREAM, {"n": 1})

    started = time.monotonic()
    messages = broker.read_blocking(STREAM, GROUP, CONSUMER, timeout_ms=TIMEOUT_MS)
    elapsed = time.monotonic() - started

    assert messages == [(identifier, {"n": 1})]
    assert elapsed < TIMEOUT_MS / 1000


@pytest.mark.requires(BrokerCapabilities.BLOCKING_READ)
def test_a_read_of_several_streams_waits_for_a_message_on_any_of_them(broker):
    other = "blocking_other_stream"
    assert broker.read_blocking_streams([STREAM, other], GROUP, CONSUMER, 0) == {
        STREAM: [],
        other: [],
    }

    publisher = threading.Timer(0.1, broker.publish, (other, {"n": 2}))
    publisher.start()
    started = time.monotonic()
    try:
        result = broker.read_blocking_streams(
            [STREAM, other], GROUP, CONSUMER, timeout_ms=TIMEOUT_MS
        )
        elapsed = time.monotonic() - started
    finally:
        publisher.join()

    assert result[STREAM] == []
    assert [message for _, message in result[other]] == [{"n": 2}]
    assert elapsed < TIMEOUT_MS / 1000
