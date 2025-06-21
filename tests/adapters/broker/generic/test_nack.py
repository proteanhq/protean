import time

import pytest


@pytest.mark.broker
def test_nack_moves_message_to_retry_queue(broker):
    """Test that nacking a message moves it to retry queue for reprocessing"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay for testing
    broker._retry_delay = 0.1  # 100ms for fast testing

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message (moves to in-flight)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    retrieved_identifier, retrieved_payload = retrieved_message
    assert retrieved_identifier == identifier
    assert retrieved_payload == message

    # Verify message is in in-flight tracking
    info_before_nack = broker.info()
    if consumer_group in info_before_nack["consumer_groups"]:
        in_flight_info = info_before_nack["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] >= 1

    # Nack the message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Message should no longer be immediately available (it's in retry queue)
    immediate_retry = broker.get_next(stream, consumer_group)
    assert immediate_retry is None

    # Verify message is removed from in-flight tracking
    info_after_nack = broker.info()
    if consumer_group in info_after_nack["consumer_groups"]:
        in_flight_info = info_after_nack["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            # Should be 0 or less than before
            assert in_flight_info[stream] == 0

    # Wait for retry delay and verify message becomes available again
    time.sleep(0.15)  # Wait slightly longer than retry delay

    # The message should now be available for retry
    retry_message = broker.get_next(stream, consumer_group)
    assert retry_message is not None
    retry_identifier, retry_payload = retry_message
    assert retry_identifier == identifier
    assert retry_payload == message


@pytest.mark.broker
def test_nack_unknown_message(broker):
    """Test that nacking an unknown message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    unknown_identifier = "unknown-message-id"

    # Ensure consumer group exists
    broker._ensure_group(consumer_group)

    # Try to nack a message that doesn't exist
    nack_result = broker.nack(stream, unknown_identifier, consumer_group)
    assert nack_result is False


@pytest.mark.broker
def test_nack_already_processed_message(broker):
    """Test that nacking an already acknowledged message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Try to nack the acknowledged message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is False


@pytest.mark.broker
def test_nack_with_retry_mechanism(broker):
    """Test that nacked messages are retried with exponential backoff"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay for testing
    broker._retry_delay = 0.1  # 100ms for fast testing

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get and nack the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Immediately trying to get next message should return None (message is in retry queue)
    immediate_retry = broker.get_next(stream, consumer_group)
    assert immediate_retry is None

    # Wait for retry delay and try again
    time.sleep(0.15)  # Wait slightly longer than retry delay

    # Now the message should be available for retry
    retry_message = broker.get_next(stream, consumer_group)
    assert retry_message is not None
    assert retry_message[0] == identifier
    assert retry_message[1] == message


@pytest.mark.broker
def test_nack_max_retries_exceeded(broker):
    """Test that messages are discarded after max retries are exceeded"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with fast retry and low max retries for testing
    broker._retry_delay = 0.01  # 10ms for very fast testing
    broker._max_retries = 2  # Only 2 retries

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack the message multiple times to exceed max retries
    for i in range(3):  # More than max_retries
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True

            # Wait for retry delay if not the last iteration
            if i < 2:
                time.sleep(0.02)

    # After max retries, the message should be discarded
    # Wait a bit more and verify no message is available
    time.sleep(0.05)
    final_check = broker.get_next(stream, consumer_group)
    assert final_check is None


@pytest.mark.broker
def test_nack_removes_from_in_flight_tracking(broker):
    """Test that nacking a message removes it from in-flight tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message1 = {"id": 1}
    message2 = {"id": 2}

    # Publish two messages
    id1 = broker.publish(stream, message1)
    broker.publish(stream, message2)

    # Get both messages (both in-flight)
    msg1 = broker.get_next(stream, consumer_group)
    msg2 = broker.get_next(stream, consumer_group)

    assert msg1 is not None
    assert msg2 is not None

    # Check broker info shows in-flight messages
    info = broker.info()
    in_flight_info = info["consumer_groups"][consumer_group].get(
        "in_flight_messages", {}
    )
    if stream in in_flight_info:
        assert in_flight_info[stream] == 2

    # Nack first message
    nack_result = broker.nack(stream, id1, consumer_group)
    assert nack_result is True

    # Check that in-flight count decreased
    info = broker.info()
    in_flight_info = info["consumer_groups"][consumer_group].get(
        "in_flight_messages", {}
    )
    if stream in in_flight_info:
        assert in_flight_info[stream] == 1


@pytest.mark.broker
def test_mixed_ack_nack_workflow(broker):
    """Test a realistic workflow with both acks and nacks"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message1 = {"id": 1, "type": "success"}
    message2 = {"id": 2, "type": "failure"}

    # Configure broker with fast retry for testing
    broker._retry_delay = 0.01

    # Publish two messages
    id1 = broker.publish(stream, message1)
    id2 = broker.publish(stream, message2)

    # Get first message and ack it (success case)
    msg1 = broker.get_next(stream, consumer_group)
    assert msg1 is not None
    assert msg1[0] == id1

    ack_result = broker.ack(stream, id1, consumer_group)
    assert ack_result is True

    # Get second message and nack it (failure case)
    msg2 = broker.get_next(stream, consumer_group)
    assert msg2 is not None
    assert msg2[0] == id2

    nack_result = broker.nack(stream, id2, consumer_group)
    assert nack_result is True

    # Wait for retry and verify second message is available again
    time.sleep(0.02)
    retry_msg = broker.get_next(stream, consumer_group)
    assert retry_msg is not None
    assert retry_msg[0] == id2


@pytest.mark.broker
def test_nack_nonexistent_consumer_group(broker):
    """Test that nacking from a non-existent consumer group returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    nonexistent_group = "nonexistent_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Try to nack from a non-existent consumer group
    nack_result = broker.nack(stream, identifier, nonexistent_group)
    assert nack_result is False


@pytest.mark.broker
def test_nack_message_ownership_validation(broker):
    """Test that messages can only be nacked by the consumer group that received them"""
    stream = "test_stream"
    consumer_group_1 = "group_1"
    consumer_group_2 = "group_2"
    message = {"foo": "bar"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Group 1 gets the message
    retrieved_message = broker.get_next(stream, consumer_group_1)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier

    # Group 2 should not be able to nack a message it didn't receive
    nack_result = broker.nack(stream, identifier, consumer_group_2)
    assert nack_result is False

    # Group 1 should be able to nack its own message
    nack_result = broker.nack(stream, identifier, consumer_group_1)
    assert nack_result is True


@pytest.mark.broker
def test_nack_dlq_functionality(broker):
    """Test Dead Letter Queue functionality when DLQ is enabled"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker for DLQ testing
    broker._retry_delay = 0.01  # Fast retries
    broker._max_retries = 1  # Only 1 retry
    broker._enable_dlq = True  # Ensure DLQ is enabled

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack the message twice to exceed max retries
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True
            if i == 0:  # Wait for first retry
                time.sleep(0.02)

    # Message should be in DLQ now
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 1
    dlq_msg = dlq_messages[stream][0]
    assert dlq_msg[0] == identifier  # identifier matches
    assert dlq_msg[1] == message  # message matches

    # Verify no more messages available for processing
    final_check = broker.get_next(stream, consumer_group)
    assert final_check is None


@pytest.mark.broker
def test_nack_dlq_disabled(broker):
    """Test behavior when DLQ is disabled - messages should be discarded"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with DLQ disabled
    broker._retry_delay = 0.01  # Fast retries
    broker._max_retries = 1  # Only 1 retry
    broker._enable_dlq = False  # Disable DLQ

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack the message twice to exceed max retries
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True
            if i == 0:  # Wait for first retry
                time.sleep(0.02)

    # No DLQ messages should exist
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 0

    # Verify no more messages available for processing
    final_check = broker.get_next(stream, consumer_group)
    assert final_check is None


@pytest.mark.broker
def test_nack_retry_count_tracking(broker):
    """Test that retry counts are properly tracked across nacks"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker for testing
    broker._retry_delay = 0.01  # Fast retries
    broker._max_retries = 3  # Allow multiple retries

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack the message multiple times and check retry progression
    for expected_retry_count in range(1, 4):  # 1, 2, 3 retries
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is True

        # Check retry count if accessible
        retry_count = broker._get_retry_count(stream, consumer_group, identifier)
        assert retry_count == expected_retry_count

        # Wait for retry if not the last iteration
        if expected_retry_count < 3:
            time.sleep(0.02)


@pytest.mark.broker
def test_nack_with_invalid_consumer_group(broker):
    """Test nack with non-existent consumer group"""
    stream = "test_stream"
    identifier = "test-id"
    consumer_group = "non-existent-group"

    result = broker.nack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.broker
def test_nack_with_wrong_message_ownership(broker):
    """Test nack with message not owned by consumer group"""
    stream = "test_stream"
    consumer_group = "test_group"
    other_group = "other_group"
    message = {"data": "test"}

    # Publish and consume with different group
    identifier = broker.publish(stream, message)
    broker.get_next(stream, other_group)  # Different group consumes

    # Try to nack with original group
    result = broker.nack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.broker
def test_nack_message_already_nacked_idempotent(broker):
    """Test nack idempotency when message already nacked"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Nack once
    result1 = broker.nack(stream, identifier, consumer_group)
    assert result1 is True

    # Try to nack again - should be idempotent
    result2 = broker.nack(stream, identifier, consumer_group)
    assert result2 is False


@pytest.mark.broker
def test_nack_message_already_acknowledged(broker):
    """Test nack when message already acknowledged"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Acknowledge first
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Try to nack after ack - should fail
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is False
