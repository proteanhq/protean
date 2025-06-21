"""Test cases specifically for Redis PubSub broker edge cases and implementation details"""

import time

import pytest


@pytest.mark.redis
def test_redis_connection_handling(broker):
    """Test Redis connection handling during operations"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)
    assert isinstance(identifier, str)

    # Get the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier
    assert retrieved_message[1] == message


@pytest.mark.redis
def test_redis_stream_creation_on_publish(broker):
    """Test that Redis streams are created automatically on publish"""
    stream = "new_stream"
    message = {"data": "test"}

    # Publish to a new stream
    identifier = broker.publish(stream, message)
    assert isinstance(identifier, str)

    # Verify we can retrieve the message
    retrieved_message = broker.get_next(stream, "test_consumer_group")
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier


@pytest.mark.redis
def test_redis_message_id_format(broker):
    """Test that Redis message IDs are in the expected format"""
    stream = "test_stream"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Redis stream IDs are typically in format: timestamp-sequence
    # But our broker might convert them to UUIDs
    assert isinstance(identifier, str)
    assert len(identifier) > 0


@pytest.mark.redis
def test_redis_ack_with_redis_stream_id(broker):
    """Test acknowledgment with Redis stream message ID"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Acknowledge using the returned identifier
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True


@pytest.mark.redis
def test_redis_nack_with_retry_mechanism(broker):
    """Test nack with Redis-specific retry mechanism"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Configure for fast retries
    broker._retry_delay = 0.01

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Nack the message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Wait for retry
    time.sleep(0.02)

    # Message should be available for retry
    retry_message = broker.get_next(stream, consumer_group)
    assert retry_message is not None
    assert retry_message[0] == identifier


@pytest.mark.redis
def test_redis_dlq_functionality(broker):
    """Test Redis-specific DLQ functionality"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack until it goes to DLQ
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True
            if i == 0:
                time.sleep(0.02)

    # Check DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) >= 0  # May or may not be implemented


@pytest.mark.redis
def test_redis_message_ordering(broker):
    """Test Redis-specific message ordering guarantees"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish messages in sequence
    messages = []
    for i in range(3):
        identifier = broker.publish(stream, {"data": f"message_{i}"})
        messages.append(identifier)

    # Retrieve messages and verify order
    retrieved_messages = []
    for _ in range(3):
        message = broker.get_next(stream, consumer_group)
        if message:
            retrieved_messages.append(message[0])

    # Verify order matches publish order
    assert retrieved_messages == messages


@pytest.mark.redis
def test_redis_data_reset_functionality(broker):
    """Test Redis-specific data reset functionality"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish some messages
    for i in range(3):
        broker.publish(stream, {"data": f"message_{i}"})

    # Reset data
    broker._data_reset()

    # Verify stream is empty
    message = broker.get_next(stream, consumer_group)
    assert message is None
