"""Tests for DLQ management API in InlineBroker."""

import time


def test_dlq_list_returns_entries_across_streams(broker):
    """Test dlq_list returns entries from multiple streams."""
    broker._max_retries = 0

    # Publish to two streams and NACK both
    id1 = broker.publish("stream1", {"data": "one"})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", id1, "group1")

    id2 = broker.publish("stream2", {"data": "two"})
    broker.get_next("stream2", "group1")
    broker.nack("stream2", id2, "group1")

    entries = broker.dlq_list(["stream1:dlq", "stream2:dlq"])
    assert len(entries) == 2
    streams = {e.stream for e in entries}
    assert streams == {"stream1", "stream2"}


def test_dlq_list_with_limit(broker):
    """Test dlq_list respects the limit parameter."""
    broker._max_retries = 0

    for i in range(5):
        msg_id = broker.publish("stream1", {"i": i})
        broker.get_next("stream1", "group1")
        broker.nack("stream1", msg_id, "group1")

    entries = broker.dlq_list(["stream1:dlq"], limit=3)
    assert len(entries) == 3


def test_dlq_list_empty_returns_empty(broker):
    """Test dlq_list with no messages returns empty list."""
    entries = broker.dlq_list(["nonexistent:dlq"])
    assert entries == []


def test_dlq_list_filters_by_stream(broker):
    """Test dlq_list only returns entries for requested streams."""
    broker._max_retries = 0

    id1 = broker.publish("stream1", {"data": "one"})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", id1, "group1")

    id2 = broker.publish("stream2", {"data": "two"})
    broker.get_next("stream2", "group1")
    broker.nack("stream2", id2, "group1")

    entries = broker.dlq_list(["stream1:dlq"])
    assert len(entries) == 1
    assert entries[0].stream == "stream1"


def test_dlq_inspect_found(broker):
    """Test dlq_inspect returns entry when found."""
    broker._max_retries = 0

    msg_id = broker.publish("stream1", {"key": "value"})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", msg_id, "group1")

    entry = broker.dlq_inspect("stream1:dlq", msg_id)
    assert entry is not None
    assert entry.dlq_id == msg_id
    assert entry.original_id == msg_id
    assert entry.stream == "stream1"
    assert entry.consumer_group == "group1"
    assert entry.payload == {"key": "value"}
    assert entry.failure_reason == "max_retries_exceeded"
    assert entry.failed_at is not None
    assert entry.dlq_stream == "stream1:dlq"


def test_dlq_inspect_not_found(broker):
    """Test dlq_inspect returns None when not found."""
    entry = broker.dlq_inspect("stream1:dlq", "nonexistent-id")
    assert entry is None


def test_dlq_inspect_wrong_stream(broker):
    """Test dlq_inspect returns None when searching wrong stream."""
    broker._max_retries = 0

    msg_id = broker.publish("stream1", {"key": "value"})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", msg_id, "group1")

    entry = broker.dlq_inspect("stream2:dlq", msg_id)
    assert entry is None


def test_dlq_replay_success(broker):
    """Test dlq_replay moves message back to target stream."""
    broker._max_retries = 0

    msg_id = broker.publish("stream1", {"key": "value"})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", msg_id, "group1")

    # Verify in DLQ
    assert len(broker.dlq_list(["stream1:dlq"])) == 1

    # Replay to target stream
    result = broker.dlq_replay("stream1:dlq", msg_id, "stream1")
    assert result is True

    # DLQ should be empty
    assert len(broker.dlq_list(["stream1:dlq"])) == 0

    # Message should be available on the target stream for new consumers
    # (It was published as a new message)
    retrieved = broker.get_next("stream1", "new_consumer")
    assert retrieved is not None
    _, msg = retrieved
    assert msg == {"key": "value"}


def test_dlq_replay_not_found(broker):
    """Test dlq_replay returns False when message doesn't exist."""
    result = broker.dlq_replay("stream1:dlq", "nonexistent", "stream1")
    assert result is False


def test_dlq_replay_all_drains_stream(broker):
    """Test dlq_replay_all replays all messages and clears DLQ."""
    broker._max_retries = 0

    ids = []
    for i in range(3):
        msg_id = broker.publish("stream1", {"i": i})
        broker.get_next("stream1", "group1")
        broker.nack("stream1", msg_id, "group1")
        ids.append(msg_id)

    assert len(broker.dlq_list(["stream1:dlq"])) == 3

    count = broker.dlq_replay_all("stream1:dlq", "stream1")
    assert count == 3
    assert len(broker.dlq_list(["stream1:dlq"])) == 0


def test_dlq_replay_all_empty_stream(broker):
    """Test dlq_replay_all returns 0 for empty DLQ."""
    count = broker.dlq_replay_all("nonexistent:dlq", "stream1")
    assert count == 0


def test_dlq_purge_clears_messages(broker):
    """Test dlq_purge removes all messages from a DLQ stream."""
    broker._max_retries = 0

    for i in range(4):
        msg_id = broker.publish("stream1", {"i": i})
        broker.get_next("stream1", "group1")
        broker.nack("stream1", msg_id, "group1")

    assert len(broker.dlq_list(["stream1:dlq"])) == 4

    count = broker.dlq_purge("stream1:dlq")
    assert count == 4
    assert len(broker.dlq_list(["stream1:dlq"])) == 0


def test_dlq_purge_empty_stream(broker):
    """Test dlq_purge returns 0 for empty DLQ."""
    count = broker.dlq_purge("nonexistent:dlq")
    assert count == 0


def test_dlq_list_sorted_newest_first(broker):
    """Test dlq_list returns entries sorted by failed_at descending."""
    broker._max_retries = 0

    id1 = broker.publish("stream1", {"order": 1})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", id1, "group1")

    time.sleep(0.01)  # Small delay to ensure different timestamps

    id2 = broker.publish("stream1", {"order": 2})
    broker.get_next("stream1", "group1")
    broker.nack("stream1", id2, "group1")

    entries = broker.dlq_list(["stream1:dlq"])
    assert len(entries) == 2
    # Newest first
    assert entries[0].payload == {"order": 2}
    assert entries[1].payload == {"order": 1}


def test_dlq_capability_flag(broker):
    """Test that InlineBroker reports DEAD_LETTER_QUEUE capability."""
    from protean.port.broker import BrokerCapabilities

    assert broker.has_capability(BrokerCapabilities.DEAD_LETTER_QUEUE)
