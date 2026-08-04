"""Tests for retry mechanism and exponential backoff in InlineBroker."""

import time

from protean.adapters.broker.inline import CONSUMER_GROUP_SEPARATOR


def test_basic_retry_mechanism(broker):
    """Test basic retry mechanism after NACK."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure short retry delay
    broker._retry_delay = 0.05  # 50ms

    # Publish and get message
    identifier = broker.publish(stream, message)
    result = broker.get_next(stream, consumer_group)
    assert result is not None

    # NACK the message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Message should not be immediately available
    result = broker.get_next(stream, consumer_group)
    assert result is None

    # Wait for retry delay
    time.sleep(0.06)

    # Message should be available again
    result = broker.get_next(stream, consumer_group)
    assert result is not None
    assert result[0] == identifier
    assert result[1] == message


def test_exponential_backoff(broker):
    """Each retry waits `retry_delay * multiplier ** retries_already_made`.

    This used to sleep 40ms against a 50ms delay and assert the message was
    still withheld, so a 10ms scheduling hiccup between the `nack` and the
    `get_next` failed it. It went red about 80% of the time in isolation
    (issue #1297).

    The schedule is now read rather than raced: `nack` records the time a
    message next becomes eligible, so the delay it chose can be asserted
    exactly. Redelivery is still exercised by moving that recorded time into
    the past, which is what waiting for it would have proved.
    """
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    broker._retry_delay = 0.05
    broker._backoff_multiplier = 2.0
    broker._max_retries = 3

    identifier = broker.publish(stream, message)
    assert broker.get_next(stream, consumer_group) is not None

    for attempt in range(broker._max_retries):
        nacked_at = time.time()
        broker.nack(stream, identifier, consumer_group)

        # Still withheld: its retry time has not arrived.
        assert broker.get_next(stream, consumer_group) is None

        scheduled = _scheduled_retry_time(broker, stream, consumer_group, identifier)
        expected_delay = broker._retry_delay * broker._backoff_multiplier**attempt
        # `nacked_at` is read just before the delay is added, so the measured
        # wait is the real delay plus however long the call itself took.
        assert expected_delay <= scheduled - nacked_at < expected_delay + 0.5

        _make_retry_due(broker, stream, consumer_group, identifier)
        assert broker.get_next(stream, consumer_group) is not None


def _group_key(stream: str, consumer_group: str) -> str:
    return f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"


def _retry_queue(broker, stream: str, consumer_group: str) -> list:
    return broker._failed_messages[_group_key(stream, consumer_group)]


def _scheduled_retry_time(broker, stream, consumer_group, identifier) -> float:
    queue = _retry_queue(broker, stream, consumer_group)
    times = [entry[3] for entry in queue if entry[0] == identifier]
    assert len(times) == 1, f"expected one queued retry, found {len(times)}"
    return times[0]


def _make_retry_due(broker, stream, consumer_group, identifier) -> None:
    """Bring a queued retry forward instead of sleeping until it is due."""
    group_key = _group_key(stream, consumer_group)
    queue = _retry_queue(broker, stream, consumer_group)
    broker._failed_messages[group_key] = [
        (msg_id, msg, count, 0.0 if msg_id == identifier else due)
        for msg_id, msg, count, due in queue
    ]


def test_max_retries_enforcement(broker):
    """Test that max retries limit is enforced."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure with low max retries
    broker._retry_delay = 0.01
    broker._max_retries = 2
    broker._enable_dlq = True

    # Publish message
    identifier = broker.publish(stream, message)

    # Exhaust all retries
    for i in range(3):  # Initial + 2 retries
        # Wait for any retry delay
        if i > 0:
            time.sleep(0.02 * (2 ** (i - 1)))

        result = broker.get_next(stream, consumer_group)
        assert result is not None
        broker.nack(stream, identifier, consumer_group)

    # Message should be in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert len(dlq_messages[stream]) == 1
    assert dlq_messages[stream][0][0] == identifier

    # Message should not be available for retry
    time.sleep(0.1)
    result = broker.get_next(stream, consumer_group)
    assert result is None


def test_retry_count_persistence(broker):
    """Test that retry count persists across retries."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure retry
    broker._retry_delay = 0.01
    broker._max_retries = 5

    # Publish message
    identifier = broker.publish(stream, message)

    # Track retry counts
    expected_counts = []

    for retry_num in range(4):
        # Wait for retry if not first attempt
        if retry_num > 0:
            time.sleep(0.02 * (2 ** (retry_num - 1)))

        # Get message
        result = broker.get_next(stream, consumer_group)
        assert result is not None

        # Check retry count
        count = broker._get_retry_count(stream, consumer_group, identifier)
        expected_counts.append(count)

        # NACK to trigger retry
        broker.nack(stream, identifier, consumer_group)

    # Verify counts increased monotonically
    assert expected_counts == [0, 1, 2, 3]


def test_retry_with_multiple_messages(broker):
    """Test retry mechanism with multiple messages."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    messages = [{"id": i} for i in range(3)]

    # Configure retry with a delay large enough that NACKed messages
    # are never ready for retry before the explicit sleep below.
    broker._retry_delay = 0.5

    # Publish messages
    identifiers = [broker.publish(stream, msg) for msg in messages]

    # Get and NACK all messages
    for _i in range(3):
        result = broker.get_next(stream, consumer_group)
        assert result is not None
        broker.nack(stream, result[0], consumer_group)

    # No messages immediately available
    result = broker.get_next(stream, consumer_group)
    assert result is None

    # Wait for retry delay
    time.sleep(0.6)

    # All messages should be available for retry
    retried = []
    for _ in range(3):
        result = broker.get_next(stream, consumer_group)
        assert result is not None
        retried.append(result[0])

    # All original messages should have been retried
    assert set(retried) == set(identifiers)


def test_retry_with_mixed_ack_nack(broker):
    """Test retry with some messages ACKed and some NACKed."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Configure retry with a delay large enough to avoid race conditions on slow CI
    broker._retry_delay = 0.5

    # Publish messages
    broker.publish(stream, {"id": 1})
    id2 = broker.publish(stream, {"id": 2})
    broker.publish(stream, {"id": 3})

    # Process messages
    msg1 = broker.get_next(stream, consumer_group)
    broker.ack(stream, msg1[0], consumer_group)  # ACK first

    msg2 = broker.get_next(stream, consumer_group)
    broker.nack(stream, msg2[0], consumer_group)  # NACK second

    msg3 = broker.get_next(stream, consumer_group)
    broker.ack(stream, msg3[0], consumer_group)  # ACK third

    # No messages immediately available
    result = broker.get_next(stream, consumer_group)
    assert result is None

    # Wait for retry
    time.sleep(0.6)

    # Only NACKed message should be available
    result = broker.get_next(stream, consumer_group)
    assert result is not None
    assert result[0] == id2

    # No more messages
    result = broker.get_next(stream, consumer_group)
    assert result is None


def test_retry_cleanup_on_ack(broker):
    """Test that retry count is cleaned up on ACK."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure retry
    broker._retry_delay = 0.01

    # Publish message
    identifier = broker.publish(stream, message)

    # Get and NACK to create retry count
    result = broker.get_next(stream, consumer_group)
    broker.nack(stream, identifier, consumer_group)

    # Verify retry count exists
    count = broker._get_retry_count(stream, consumer_group, identifier)
    assert count == 1

    # Wait and get message again
    time.sleep(0.02)
    result = broker.get_next(stream, consumer_group)
    assert result is not None

    # ACK the message
    broker.ack(stream, identifier, consumer_group)

    # Retry count should be cleaned up
    count = broker._get_retry_count(stream, consumer_group, identifier)
    assert count == 0


def test_retry_failed_message_structure(broker):
    """Test the structure of failed messages awaiting retry."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"test": "data"}

    # Configure retry
    broker._retry_delay = 0.05

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # NACK to create failed message
    broker.nack(stream, identifier, consumer_group)

    # Check failed message structure
    group_key = f"{stream}:{consumer_group}"
    assert len(broker._failed_messages[group_key]) == 1

    failed_msg = broker._failed_messages[group_key][0]
    assert failed_msg[0] == identifier  # Message ID
    assert failed_msg[1] == message  # Message content
    assert failed_msg[2] == 1  # Retry count
    assert isinstance(failed_msg[3], float)  # Next retry time
    assert failed_msg[3] > time.time()  # Future retry time


def test_get_retry_ready_messages(broker):
    """Test getting messages ready for retry."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Configure short retry with enough buffer
    broker._retry_delay = 0.05  # 50ms retry delay

    # Publish and NACK multiple messages
    ids = []
    messages = []
    for i in range(3):
        msg = {"id": i}
        msg_id = broker.publish(stream, msg)
        ids.append(msg_id)
        messages.append(msg)

        broker.get_next(stream, consumer_group)
        broker.nack(stream, msg_id, consumer_group)

    # Initially no messages ready (they all have future retry times)
    ready = broker._get_retry_ready_messages(stream, consumer_group)
    assert len(ready) == 0

    # Wait for messages to be ready
    time.sleep(0.06)  # Wait longer than retry delay
    ready = broker._get_retry_ready_messages(stream, consumer_group)
    assert len(ready) == 3

    # Verify message IDs match
    ready_ids = [msg[0] for msg in ready]
    assert set(ready_ids) == set(ids)


def test_cleanup_operations_during_nack(broker):
    """Test that cleanup operations work correctly during NACK."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Verify message is in-flight before NACK
    assert broker._is_in_flight_message(stream, consumer_group, identifier)

    # NACK the message
    broker.nack(stream, identifier, consumer_group)

    # Verify cleanup occurred
    assert not broker._is_in_flight_message(stream, consumer_group, identifier)

    # Verify message is in failed queue
    group_key = f"{stream}:{consumer_group}"
    assert len(broker._failed_messages[group_key]) == 1
    assert broker._failed_messages[group_key][0][0] == identifier
