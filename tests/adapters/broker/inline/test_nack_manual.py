import time


def test_nack_moves_message_to_retry_queue(broker):
    """Test that nacking a message moves it to retry queue for reprocessing (reliable messaging specific)"""
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


def test_nack_with_retry_mechanism(broker):
    """Test that nacked messages are retried with exponential backoff (reliable messaging specific)"""
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


def test_nack_max_retries_exceeded(broker):
    """Test that messages are discarded after max retries are exceeded (reliable messaging specific)"""
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


def test_nack_removes_from_in_flight_tracking(broker):
    """Test that nacking a message removes it from in-flight tracking (reliable messaging specific)"""
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


def test_nack_retry_count_tracking(broker):
    """Test that retry counts are properly tracked for nacked messages (reliable messaging specific)"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "retry_test"}

    # Configure broker with fast retry for testing
    broker._retry_delay = 0.01
    broker._max_retries = 3

    # Publish a message
    identifier = broker.publish(stream, message)

    # Track retries
    for retry_num in range(3):
        # Get and nack the message
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is True

        # Wait for retry delay
        time.sleep(0.02)

    # After 3 retries, message should be exhausted
    final_check = broker.get_next(stream, consumer_group)
    assert final_check is None


def test_nack_message_already_nacked_idempotent(broker):
    """Test nack idempotency when message already nacked (reliable messaging specific)"""
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
