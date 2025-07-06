"""Test cases specifically for Redis PubSub broker edge cases and Redis-specific behavior"""

import pytest


@pytest.mark.redis
def test_redis_connection_during_operations(broker):
    """Test Redis connection handling during broker operations"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)
    assert isinstance(identifier, str)
    assert len(identifier) > 0

    # Get the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier
    assert retrieved_message[1] == message


@pytest.mark.redis
def test_redis_message_id_uuid_format(broker):
    """Test that Redis broker generates proper UUID format identifiers"""
    stream = "test_stream"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Should be a UUID string
    assert isinstance(identifier, str)
    assert len(identifier) == 36  # UUID string length
    assert identifier.count("-") == 4  # UUID has 4 hyphens

    # Test multiple UUIDs are unique
    identifier2 = broker.publish(stream, {"data": "test2"})
    assert identifier != identifier2


@pytest.mark.redis
def test_ack_nack_not_supported_simple_queuing(broker):
    """Test that ACK/NACK operations are not supported in simple queuing mode"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # ACK should not be supported
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is False

    # NACK should not be supported
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is False


@pytest.mark.redis
def test_redis_consumer_group_internal_tracking(broker):
    """Test Redis-specific consumer group internal tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message to create consumer group
    broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Check internal tracking exists
    group_key = f"{stream}:{consumer_group}"
    assert group_key in broker._consumer_groups
    assert "created_at" in broker._consumer_groups[group_key]
    assert "consumers" in broker._consumer_groups[group_key]


@pytest.mark.redis
def test_redis_position_key_tracking(broker):
    """Test Redis-specific position key tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Check Redis position key
    position_key = f"position:{stream}:{consumer_group}"
    position = broker.redis_instance.get(position_key)
    assert position is not None
    assert int(position) == 1  # Should be incremented


@pytest.mark.redis
def test_redis_data_reset_clears_internal_state(broker):
    """Test Redis data reset clears both Redis and internal broker state"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Create some data
    broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Verify data exists
    assert broker.redis_instance.llen(stream) > 0
    assert len(broker._consumer_groups) > 0

    # Reset data
    broker._data_reset()

    # Verify both Redis and internal state are cleared
    assert broker.redis_instance.llen(stream) == 0
    assert len(broker._consumer_groups) == 0


@pytest.mark.redis
def test_redis_independent_consumer_group_positions(broker):
    """Test that Redis tracks independent positions for different consumer groups"""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"

    # Publish messages
    for i in range(3):
        broker.publish(stream, {"data": f"message_{i}"})

    # Group 1 reads first message
    msg1 = broker.get_next(stream, consumer_group1)
    assert msg1 is not None

    # Group 2 should also get first message (independent position)
    msg2 = broker.get_next(stream, consumer_group2)
    assert msg2 is not None
    assert msg2[0] == msg1[0]  # Same message

    # Check Redis position keys are independent
    position_key1 = f"position:{stream}:{consumer_group1}"
    position_key2 = f"position:{stream}:{consumer_group2}"

    position1 = broker.redis_instance.get(position_key1)
    position2 = broker.redis_instance.get(position_key2)

    assert int(position1) == 1  # Group 1 has advanced
    assert int(position2) == 1  # Group 2 has also advanced
