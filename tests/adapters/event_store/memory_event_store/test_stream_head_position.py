"""Tests for stream_head_position() on the memory event store adapter."""


def _create_test_metadata(stream_name, message_type, message_id=None):
    """Helper to create metadata with required headers for tests."""
    return {
        "domain": {"kind": "EVENT"},
        "headers": {
            "id": message_id or f"{stream_name}-{message_type}",
            "type": message_type,
            "stream": stream_name,
        },
    }


def test_empty_stream_returns_minus_one(test_domain):
    """stream_head_position returns -1 for a stream with no messages."""
    store = test_domain.event_store.store
    result = store.stream_head_position("nonexistent")
    assert result == -1


def test_single_message(test_domain):
    """stream_head_position returns the global_position of the only message."""
    store = test_domain.event_store.store
    store.write_message(
        "testStream-123",
        "Event1",
        {"foo": "bar"},
        _create_test_metadata("testStream-123", "Event1"),
    )

    result = store.stream_head_position("testStream")
    assert result >= 0


def test_multiple_messages_returns_latest(test_domain):
    """stream_head_position returns the global_position of the last message."""
    store = test_domain.event_store.store

    for i in range(5):
        store.write_message(
            "testStream-123",
            "Event1",
            {"count": i},
            _create_test_metadata("testStream-123", "Event1", f"msg-{i}"),
        )

    result = store.stream_head_position("testStream")

    # Read all to verify it's the position of the last message
    all_msgs = store.get_category_messages("testStream", limit=1_000_000)
    expected = all_msgs[-1].get("global_position", -1)
    assert result == expected


def test_head_position_with_multiple_streams(test_domain):
    """stream_head_position returns the correct head per category."""
    store = test_domain.event_store.store

    # Write to stream A
    for i in range(3):
        store.write_message(
            f"streamA-{i}",
            "EventA",
            {"idx": i},
            _create_test_metadata(f"streamA-{i}", "EventA", f"a-{i}"),
        )

    # Write to stream B
    for i in range(2):
        store.write_message(
            f"streamB-{i}",
            "EventB",
            {"idx": i},
            _create_test_metadata(f"streamB-{i}", "EventB", f"b-{i}"),
        )

    head_a = store.stream_head_position("streamA")
    head_b = store.stream_head_position("streamB")

    all_a = store.get_category_messages("streamA", limit=1_000_000)
    all_b = store.get_category_messages("streamB", limit=1_000_000)

    assert head_a == all_a[-1]["global_position"]
    assert head_b == all_b[-1]["global_position"]
    assert head_a != head_b
