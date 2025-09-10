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


def test_reading_stream_message(test_domain):
    test_domain.event_store.store._write(
        "testStream-123",
        "Event1",
        {"foo": "bar"},
        _create_test_metadata("testStream-123", "Event1"),
    )

    messages = test_domain.event_store.store._read("testStream-123")

    assert len(messages) == 1
    assert messages[0]["position"] == 0
    assert messages[0]["data"] == {"foo": "bar"}


def test_reading_multiple_stream_messages(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123",
            "Event1",
            {"foo": f"bar{i}"},
            _create_test_metadata("testStream-123", "Event1", f"msg-{i}"),
        )

    messages = test_domain.event_store.store._read("testStream-123")

    assert len(messages) == 5
    assert messages[4]["data"] == {"foo": "bar4"}


def test_reading_category_message(test_domain):
    test_domain.event_store.store._write(
        "testStream-123",
        "Event1",
        {"foo": "bar"},
        _create_test_metadata("testStream-123", "Event1"),
    )

    messages = test_domain.event_store.store._read("testStream")

    assert len(messages) == 1
    assert messages[0]["position"] == 0
    assert messages[0]["data"] == {"foo": "bar"}


def test_reading_multiple_category_messages(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123",
            "Event1",
            {"foo": f"bar{i}"},
            _create_test_metadata("testStream-123", "Event1", f"cat-msg-{i}"),
        )

    messages = test_domain.event_store.store._read("testStream")

    assert len(messages) == 5
    assert messages[4]["data"] == {"foo": "bar4"}


def test_reading_targeted_stream_messages(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123",
            "Event1",
            {"foo": f"bar{i}"},
            _create_test_metadata("testStream-123", "Event1", f"stream1-msg-{i}"),
        )
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-456",
            "Event1",
            {"foo": f"baz{i}"},
            _create_test_metadata("testStream-456", "Event1", f"stream2-msg-{i}"),
        )

    messages = test_domain.event_store.store._read("testStream-456")

    assert len(messages) == 5
    assert messages[4]["data"] == {"foo": "baz4"}


def test_read_last_message(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123",
            "Event1",
            {"foo": f"bar{i}"},
            _create_test_metadata("testStream-123", "Event1", f"last-msg-{i}"),
        )

    message = test_domain.event_store.store._read_last_message("testStream-123")
    assert message["position"] == 4


def test_read_last_message_when_there_are_no_messages(test_domain):
    message = test_domain.event_store.store._read_last_message("foo-bar")
    assert message is None
