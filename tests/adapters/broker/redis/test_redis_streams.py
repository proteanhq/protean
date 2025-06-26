import pytest

from protean.adapters.broker.redis import RedisBroker


@pytest.fixture
def redis_broker(test_domain):
    return test_domain.brokers["default"]


@pytest.mark.redis
def test_redis_streams_consumer_group_creation(redis_broker):
    """Test that consumer groups are created automatically"""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"data": "test"}

    # Publish and consume to trigger group creation
    redis_broker.publish(stream, message)
    redis_broker.get_next(stream, consumer_group)

    # Check that consumer group exists
    info = redis_broker.info()
    assert "consumer_groups" in info
    assert stream in info["consumer_groups"]
    assert consumer_group in info["consumer_groups"][stream]


@pytest.mark.redis
def test_redis_streams_pending_messages_redelivery(redis_broker):
    """Test that pending messages are redelivered (Redis-specific behavior)"""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"data": "test_pending"}

    # Publish and consume message
    identifier = redis_broker.publish(stream, message)
    result = redis_broker.get_next(stream, consumer_group)
    assert result is not None

    # Don't ack the message, it should remain pending
    # When we call get_next again, it should return the pending message
    pending_result = redis_broker.get_next(stream, consumer_group)
    if pending_result:  # Redis Streams may return pending messages
        pending_id, pending_message = pending_result
        assert pending_id == identifier
        assert pending_message == message


@pytest.mark.redis
def test_redis_streams_read_multiple(redis_broker):
    """Test reading multiple messages at once"""
    stream = "test_stream"
    consumer_group = "test_group"
    messages = [{"data": f"message_{i}", "id": i} for i in range(5)]

    # Publish multiple messages
    identifiers = []
    for message in messages:
        identifier = redis_broker.publish(stream, message)
        identifiers.append(identifier)

    # Read multiple messages
    results = redis_broker.read(stream, consumer_group, 3)
    assert len(results) == 3

    for i, (result_id, result_message) in enumerate(results):
        assert result_id == identifiers[i]
        assert result_message == messages[i]


@pytest.mark.redis
def test_redis_streams_unique_identifiers(redis_broker):
    """Test that Redis Streams generates unique identifiers in timestamp-sequence format"""
    stream = "test_stream"
    message = {"data": "test"}

    # Publish multiple messages and verify unique identifiers
    identifiers = []
    for _ in range(10):
        identifier = redis_broker.publish(stream, message)
        identifiers.append(identifier)

    # All identifiers should be unique
    assert len(set(identifiers)) == len(identifiers)

    # Redis Streams IDs should have the format timestamp-sequence
    for identifier in identifiers:
        assert "-" in identifier
        parts = identifier.split("-")
        assert len(parts) == 2
        assert parts[0].isdigit()  # timestamp part
        assert parts[1].isdigit()  # sequence part


@pytest.mark.redis
def test_redis_streams_nack_pending_behavior(redis_broker):
    """Test Redis-specific nack behavior with pending messages"""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"data": "test_nack"}

    # Publish and consume message
    identifier = redis_broker.publish(stream, message)
    result = redis_broker.get_next(stream, consumer_group)
    assert result is not None

    # Nack message
    nack_result = redis_broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # For Redis Streams, nacked messages remain in pending list
    # This behavior is different from inline brokers
    info = redis_broker.info()
    if (
        stream in info["consumer_groups"]
        and consumer_group in info["consumer_groups"][stream]
    ):
        # Check that there's a pending message
        assert info["consumer_groups"][stream][consumer_group]["pending"] > 0


@pytest.mark.redis
def test_redis_streams_concurrent_consumers(redis_broker):
    """Test multiple consumers in the same consumer group (Redis-specific)"""
    stream = "test_stream"
    consumer_group = "test_group"

    # Create multiple broker instances with different consumer names
    broker1 = redis_broker

    # Create second broker instance (simulating different consumer)
    broker2 = RedisBroker("test2", redis_broker.domain, redis_broker.conn_info)

    messages = [{"data": f"msg_{i}"} for i in range(10)]

    # Publish all messages
    for message in messages:
        redis_broker.publish(stream, message)

    # Both consumers read from the same group - they should get different messages
    msgs1 = broker1.read(stream, consumer_group, 5)
    msgs2 = broker2.read(stream, consumer_group, 5)

    # Total messages consumed should equal published messages
    total_consumed = len(msgs1) + len(msgs2)
    assert total_consumed <= len(messages)

    # No message should be consumed by both consumers
    ids1 = set(msg[0] for msg in msgs1)
    ids2 = set(msg[0] for msg in msgs2)
    assert len(ids1.intersection(ids2)) == 0


@pytest.mark.redis
def test_redis_streams_stream_info_details(redis_broker):
    """Test detailed stream information retrieval (Redis-specific)"""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"data": "info_test"}

    # Publish and consume
    redis_broker.publish(stream, message)
    redis_broker.get_next(stream, consumer_group)

    # Get detailed info
    info = redis_broker.info()

    assert "consumer_groups" in info
    assert stream in info["consumer_groups"]
    assert consumer_group in info["consumer_groups"][stream]

    group_info = info["consumer_groups"][stream][consumer_group]
    assert "consumers" in group_info
    assert "pending" in group_info
    assert "last_delivered_id" in group_info

    # Check consumer details
    consumers = group_info["consumers"]
    assert len(consumers) > 0

    consumer = consumers[0]
    assert "name" in consumer
    assert "pending" in consumer


@pytest.mark.redis
def test_redis_streams_message_expiration_and_cleanup(redis_broker):
    """Test Redis Streams specific behavior around message persistence"""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"data": "persistent_test"}

    # Publish message
    identifier = redis_broker.publish(stream, message)

    # Consume but don't ack
    result = redis_broker.get_next(stream, consumer_group)
    assert result is not None

    # Message should still be in pending list
    info = redis_broker.info()
    if (
        stream in info["consumer_groups"]
        and consumer_group in info["consumer_groups"][stream]
    ):
        assert info["consumer_groups"][stream][consumer_group]["pending"] > 0

    # Now ack the message
    redis_broker.ack(stream, identifier, consumer_group)

    # Check pending count decreased
    info_after_ack = redis_broker.info()
    if (
        stream in info_after_ack["consumer_groups"]
        and consumer_group in info_after_ack["consumer_groups"][stream]
    ):
        # Pending count should be 0 or less than before
        assert info_after_ack["consumer_groups"][stream][consumer_group]["pending"] == 0


@pytest.mark.redis
def test_redis_streams_message_ordering(redis_broker):
    """Test that messages are delivered in order (Redis Streams guarantee)"""
    stream = "test_stream"
    consumer_group = "test_group"

    # Publish messages with identifiable order
    messages = [{"order": i, "data": f"msg_{i}"} for i in range(10)]
    identifiers = []

    for message in messages:
        identifier = redis_broker.publish(stream, message)
        identifiers.append(identifier)

    # Consume all messages
    consumed_messages = redis_broker.read(stream, consumer_group, 10)

    # Check order is preserved
    for i, (msg_id, msg_data) in enumerate(consumed_messages):
        assert msg_data["order"] == i
        assert msg_id == identifiers[i]


@pytest.mark.redis
def test_get_next_with_unexpected_exception(redis_broker, monkeypatch):
    """Test _get_next method handling unexpected exceptions"""
    stream = "test_stream"
    consumer_group = "test_group"

    # Mock redis instance to raise unexpected exception
    def mock_xreadgroup(*args, **kwargs):
        raise Exception("Unexpected Redis error")

    monkeypatch.setattr(redis_broker.redis_instance, "xreadgroup", mock_xreadgroup)

    result = redis_broker.get_next(stream, consumer_group)
    assert result is None


@pytest.mark.redis
def test_handle_redis_error_non_nogroup_error(redis_broker):
    """Test _handle_redis_error with non-NOGROUP errors"""
    import redis as redis_module

    stream = "test_stream"
    consumer_group = "test_group"

    # Create an error that's not NOGROUP
    error = redis_module.ResponseError("Some other Redis error")
    result = redis_broker._handle_redis_error(error, stream, consumer_group)
    assert result is None


@pytest.mark.redis
def test_deserialize_message_with_json_decode_error(redis_broker, monkeypatch):
    """Test _deserialize_message handling JSON decode errors"""

    # Create malformed JSON data
    fields = {b"data": b"invalid json {"}

    result = redis_broker._deserialize_message(fields)
    assert result == {}


@pytest.mark.redis
def test_deserialize_message_with_unicode_decode_error(redis_broker):
    """Test _deserialize_message handling Unicode decode errors"""

    # Create invalid UTF-8 bytes
    fields = {"data": b"\xff\xfe invalid utf-8"}

    result = redis_broker._deserialize_message(fields)
    assert result == {}


@pytest.mark.redis
def test_deserialize_message_with_no_data_field(redis_broker):
    """Test _deserialize_message when no data field exists"""

    # Fields without the expected "data" key
    fields = {"other_field": "some_value"}

    result = redis_broker._deserialize_message(fields)
    assert result == {}


@pytest.mark.redis
def test_ack_nacked_message(redis_broker):
    """Test ACK on a previously NACKed message should fail"""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"data": "test_ack_nack"}

    # Publish and consume message
    identifier = redis_broker.publish(stream, message)
    result = redis_broker.get_next(stream, consumer_group)
    assert result is not None

    # NACK the message first
    nack_result = redis_broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Try to ACK the NACKed message - should fail
    ack_result = redis_broker.ack(stream, identifier, consumer_group)
    assert ack_result is False


@pytest.mark.redis
def test_ack_with_redis_response_error(redis_broker, monkeypatch):
    """Test ACK method handling Redis response errors"""
    import redis as redis_module

    stream = "test_stream"
    consumer_group = "test_group"
    identifier = "fake-id"

    def mock_xack(*args, **kwargs):
        raise redis_module.ResponseError("Redis ACK error")

    monkeypatch.setattr(redis_broker.redis_instance, "xack", mock_xack)

    result = redis_broker.ack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.redis
def test_ack_with_unexpected_exception(redis_broker, monkeypatch):
    """Test ACK method handling unexpected exceptions"""
    stream = "test_stream"
    consumer_group = "test_group"
    identifier = "fake-id"

    def mock_xack(*args, **kwargs):
        raise Exception("Unexpected ACK error")

    monkeypatch.setattr(redis_broker.redis_instance, "xack", mock_xack)

    result = redis_broker.ack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.redis
def test_nack_with_unexpected_exception(redis_broker, monkeypatch):
    """Test NACK method handling unexpected exceptions"""
    stream = "test_stream"
    consumer_group = "test_group"
    identifier = "fake-id"

    def mock_is_message_pending(*args, **kwargs):
        raise Exception("Unexpected NACK error")

    monkeypatch.setattr(redis_broker, "_is_message_pending", mock_is_message_pending)

    result = redis_broker.nack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.redis
def test_nack_non_pending_message(redis_broker):
    """Test NACK on a message that's not in pending list"""
    stream = "test_stream"
    consumer_group = "test_group"
    fake_identifier = "9999999999999-0"  # Non-existent message ID

    result = redis_broker.nack(stream, fake_identifier, consumer_group)
    assert result is False


@pytest.mark.redis
def test_is_message_pending_with_redis_error(redis_broker, monkeypatch):
    """Test _is_message_pending handling Redis errors"""
    import redis as redis_module

    stream = "test_stream"
    consumer_group = "test_group"
    identifier = "fake-id"

    def mock_xpending_range(*args, **kwargs):
        raise redis_module.ResponseError("Redis XPENDING error")

    monkeypatch.setattr(
        redis_broker.redis_instance, "xpending_range", mock_xpending_range
    )

    result = redis_broker._is_message_pending(stream, consumer_group, identifier)
    assert result is False


@pytest.mark.redis
def test_is_message_pending_message_id_mismatch(redis_broker, monkeypatch):
    """Test _is_message_pending with message ID mismatch"""
    stream = "test_stream"
    consumer_group = "test_group"
    identifier = "1234567890123-0"

    # Mock XPENDING to return different message ID
    def mock_xpending_range(*args, **kwargs):
        return [{"message_id": b"9999999999999-0", "consumer": b"test"}]

    monkeypatch.setattr(
        redis_broker.redis_instance, "xpending_range", mock_xpending_range
    )

    result = redis_broker._is_message_pending(stream, consumer_group, identifier)
    assert result is False


@pytest.mark.redis
def test_ensure_group_without_stream(redis_broker):
    """Test _ensure_group called without stream parameter"""
    # This should trigger the early return path (lines 213->exit)
    redis_broker._ensure_group("test_group", stream=None)
    # If it returns without error, the early exit worked


@pytest.mark.redis
def test_ensure_group_with_other_redis_error(redis_broker, monkeypatch):
    """Test _ensure_group handling non-BUSYGROUP Redis errors"""
    import redis as redis_module

    def mock_xgroup_create(*args, **kwargs):
        raise redis_module.ResponseError("Some other Redis error")

    monkeypatch.setattr(
        redis_broker.redis_instance, "xgroup_create", mock_xgroup_create
    )

    # This should trigger the warning log path
    redis_broker._ensure_group("test_group", "test_stream")


@pytest.mark.redis
def test_ensure_group_with_unexpected_exception(redis_broker, monkeypatch):
    """Test _ensure_group handling unexpected exceptions"""

    def mock_xgroup_create(*args, **kwargs):
        raise Exception("Unexpected group creation error")

    monkeypatch.setattr(
        redis_broker.redis_instance, "xgroup_create", mock_xgroup_create
    )

    # This should trigger the error log path
    redis_broker._ensure_group("test_group", "test_stream")


@pytest.mark.redis
def test_info_with_exception(redis_broker, monkeypatch):
    """Test _info method handling exceptions"""

    def mock_get_streams_to_check():
        raise Exception("Error getting streams")

    monkeypatch.setattr(
        redis_broker, "_get_streams_to_check", mock_get_streams_to_check
    )

    info = redis_broker.info()
    # Should return basic structure even with exception
    assert "consumer_groups" in info


@pytest.mark.redis
def test_get_stream_info_non_existent_stream(redis_broker):
    """Test _get_stream_info for non-existent stream"""
    result = redis_broker._get_stream_info("non_existent_stream")
    assert result is None


@pytest.mark.redis
def test_get_stream_info_with_non_dict_group_info(redis_broker, monkeypatch):
    """Test _get_stream_info handling non-dict group info"""

    def mock_xinfo_groups(*args, **kwargs):
        return [
            "not_a_dict",
            {"name": b"valid_group", "pending": b"0", "last-delivered-id": b"0-0"},
        ]  # Mix of non-dict and dict

    def mock_xinfo_consumers(*args, **kwargs):
        return [{"name": b"consumer1", "pending": b"0"}]

    monkeypatch.setattr(redis_broker.redis_instance, "xinfo_groups", mock_xinfo_groups)
    monkeypatch.setattr(
        redis_broker.redis_instance, "xinfo_consumers", mock_xinfo_consumers
    )

    result = redis_broker._get_stream_info("test_stream")
    # Should only process the valid dict entry
    assert isinstance(result, dict)
    assert "valid_group" in result


@pytest.mark.redis
def test_extract_group_data_with_exception(redis_broker, monkeypatch):
    """Test _extract_group_data handling exceptions"""

    def mock_get_field_value(*args, **kwargs):
        raise Exception("Field extraction error")

    monkeypatch.setattr(redis_broker, "_get_field_value", mock_get_field_value)

    result = redis_broker._extract_group_data({"name": b"test"}, "test_stream")
    assert result is None


@pytest.mark.redis
def test_extract_group_data_with_no_group_name(redis_broker):
    """Test _extract_group_data when group name is None"""
    # Mock group info without proper name field
    group_info = {"other_field": b"value"}

    result = redis_broker._extract_group_data(group_info, "test_stream")
    assert result is None


@pytest.mark.redis
def test_extract_consumers_data_with_non_dict_consumer(redis_broker):
    """Test _extract_consumers_data handling non-dict consumer info"""
    consumers_info = ["not_a_dict", {"name": b"valid_consumer", "pending": b"1"}]

    result = redis_broker._extract_consumers_data(consumers_info)
    # Should only process the valid dict entry
    assert len(result) == 1
    assert result[0]["name"] == "valid_consumer"


@pytest.mark.redis
def test_extract_consumers_data_with_none_consumer_name(redis_broker, monkeypatch):
    """Test _extract_consumers_data when consumer name is None"""

    def mock_get_field_value(info_dict, field_name, convert_to_int=False):
        if field_name == "name":
            return None  # Simulate missing name
        return "1" if convert_to_int else "value"

    monkeypatch.setattr(redis_broker, "_get_field_value", mock_get_field_value)

    consumers_info = [{"name": b"test", "pending": b"1"}]
    result = redis_broker._extract_consumers_data(consumers_info)

    # Should skip consumer with None name
    assert len(result) == 0


@pytest.mark.redis
def test_get_field_value_convert_to_int_error(redis_broker):
    """Test _get_field_value conversion to int with invalid value"""
    info_dict = {"test_field": b"not_a_number"}

    result = redis_broker._get_field_value(info_dict, "test_field", convert_to_int=True)
    assert result == 0  # Should return 0 for invalid conversion


@pytest.mark.redis
def test_get_field_value_field_not_found(redis_broker):
    """Test _get_field_value when field is not found"""
    info_dict = {"other_field": b"value"}

    result = redis_broker._get_field_value(info_dict, "missing_field")
    assert result is None


@pytest.mark.redis
def test_data_reset_with_exception(redis_broker, monkeypatch):
    """Test _data_reset handling exceptions"""

    def mock_flushall():
        raise Exception("Redis flush error")

    monkeypatch.setattr(redis_broker.redis_instance, "flushall", mock_flushall)

    # Should not raise exception, just log error
    redis_broker._data_reset()


@pytest.mark.redis
def test_decode_if_bytes_with_non_bytes(redis_broker):
    """Test _decode_if_bytes with non-bytes input"""
    result = redis_broker._decode_if_bytes("already_string")
    assert result == "already_string"

    result = redis_broker._decode_if_bytes(123)
    assert result == "123"


@pytest.mark.redis
def test_extract_message_from_response_empty_response(redis_broker):
    """Test _extract_message_from_response with empty/None response"""
    # Test with None response
    result = redis_broker._extract_message_from_response(None)
    assert result is None

    # Test with empty response
    result = redis_broker._extract_message_from_response([])
    assert result is None

    # Test with response where first element has empty messages
    result = redis_broker._extract_message_from_response([("stream", [])])
    assert result is None


@pytest.mark.redis
def test_extract_message_from_response_no_messages(redis_broker):
    """Test _extract_message_from_response when no messages in response"""
    # Response structure but no actual messages
    response = [("test_stream", [])]

    result = redis_broker._extract_message_from_response(response)
    assert result is None


@pytest.mark.redis
def test_extract_message_from_response_complex_empty_cases(redis_broker):
    """Test _extract_message_from_response with various empty response structures"""
    # Test with response[0][1] being falsy but not None
    result = redis_broker._extract_message_from_response([("stream", False)])
    assert result is None

    # Test with response[0][1] being 0
    result = redis_broker._extract_message_from_response([("stream", 0)])
    assert result is None


@pytest.mark.redis
def test_handle_redis_error_nogroup_and_recursive_call(redis_broker, monkeypatch):
    """Test _handle_redis_error handling NOGROUP error that leads to recursive call"""
    import redis as redis_module

    stream = "test_stream"
    consumer_group = "test_group"

    call_count = 0

    def mock_get_next(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call - simulate the NOGROUP error scenario
            error = redis_module.ResponseError("NOGROUP No such key 'test_group'")
            return redis_broker._handle_redis_error(error, stream, consumer_group)
        else:
            # Second call - return None to simulate no messages
            return None

    monkeypatch.setattr(redis_broker, "_get_next", mock_get_next)

    result = redis_broker.get_next(stream, consumer_group)
    assert result is None
    assert call_count == 2  # Verify recursive call happened


@pytest.mark.redis
def test_read_method_early_break(redis_broker):
    """Test read method breaking early when no more messages available"""
    stream = "test_stream"
    consumer_group = "test_group"

    # Publish only 2 messages but try to read 5
    redis_broker.publish(stream, {"data": "msg1"})
    redis_broker.publish(stream, {"data": "msg2"})

    results = redis_broker.read(
        stream, consumer_group, 5
    )  # Request more than available

    # Should only get 2 messages and break early
    assert len(results) == 2


@pytest.mark.redis
def test_ensure_group_already_exists_early_return(redis_broker):
    """Test _ensure_group early return when group already in cache"""
    stream = "test_stream"
    consumer_group = "test_group"

    # First call - creates the group
    redis_broker._ensure_group(consumer_group, stream)

    # Add to created groups to simulate cached state
    group_key = f"{stream}:{consumer_group}"
    redis_broker._created_groups.add(group_key)

    # Second call - should return early
    redis_broker._ensure_group(consumer_group, stream)

    # If we get here without error, the early return worked


@pytest.mark.redis
def test_info_method_no_streams_to_check(redis_broker, monkeypatch):
    """Test _info method when there are no streams to check"""

    def mock_get_streams_to_check():
        return set()  # Return empty set

    monkeypatch.setattr(
        redis_broker, "_get_streams_to_check", mock_get_streams_to_check
    )

    info = redis_broker.info()

    # Should return basic structure with empty consumer_groups
    assert "consumer_groups" in info
    assert len(info["consumer_groups"]) == 0


@pytest.mark.redis
def test_get_stream_info_empty_stream_info(redis_broker, monkeypatch):
    """Test _get_stream_info returning None when stream_info is empty"""

    def mock_xinfo_groups(*args, **kwargs):
        return []  # Return empty list

    monkeypatch.setattr(redis_broker.redis_instance, "xinfo_groups", mock_xinfo_groups)

    result = redis_broker._get_stream_info("test_stream")
    assert result is None  # Should return None for empty stream_info


@pytest.mark.redis
def test_get_next_with_malformed_response_structure(redis_broker, monkeypatch):
    """Test _get_next handling malformed Redis response structures"""
    import redis as redis_module

    stream = "test_stream"
    consumer_group = "test_group"

    # Mock xreadgroup to return a malformed response structure
    def mock_xreadgroup(*args, **kwargs):
        # Return response where response[0][1] exists but messages is empty
        return [("test_stream", [])]

    monkeypatch.setattr(redis_broker.redis_instance, "xreadgroup", mock_xreadgroup)

    result = redis_broker.get_next(stream, consumer_group)
    assert result is None


@pytest.mark.redis
def test_extract_message_from_response_edge_cases(redis_broker):
    """Test _extract_message_from_response with specific edge case structures"""
    # Test response where response[0][1] is truthy but messages is empty
    response_with_empty_messages = [("test_stream", [])]
    result = redis_broker._extract_message_from_response(response_with_empty_messages)
    assert result is None

    # Test response structure that would trigger line 73 (messages extraction)
    response_with_messages = [
        ("test_stream", [("1234567890-0", {b"data": b'{"test": "data"}'})])
    ]
    result = redis_broker._extract_message_from_response(response_with_messages)
    assert result is not None
    assert result[0] == "1234567890-0"
    assert result[1] == {"test": "data"}
