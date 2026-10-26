"""Test cases specifically for Redis PubSub broker edge cases and Redis-specific behavior"""

import logging

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

    # The identifier is what a consumer reads back with the message
    retrieved = broker.get_next(stream, "test_group")
    assert retrieved == (identifier, message)


@pytest.mark.redis
def test_ack_nack_not_supported_simple_queuing(broker, caplog):
    """Test that ACK/NACK operations are not supported in simple queuing mode"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        # ACK should not be supported
        ack_result = broker.ack(stream, identifier, consumer_group)
        assert ack_result is False

        # NACK should not be supported
        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is False

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == [
        "Broker default does not support message acknowledgment",
        "Broker default does not support message negative acknowledgment",
    ]


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
    created_at = broker._consumer_groups[group_key]["created_at"]

    # Reading again with the same group reuses its record instead of making a
    # second one
    broker.get_next(stream, consumer_group)
    assert list(broker._consumer_groups) == [group_key]
    assert broker._consumer_groups[group_key]["created_at"] == created_at

    # A second group on the same stream is tracked beside the first, and health
    # stats report both
    broker.get_next(stream, "another_group")
    consumer_groups = broker.health_stats()["details"]["consumer_groups"]
    assert consumer_groups == {
        "count": 2,
        "names": [group_key, f"{stream}:another_group"],
    }


@pytest.mark.redis
def test_redis_position_key_tracking(broker):
    """Test Redis-specific position key tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish two messages and read the first
    first = broker.publish(stream, message)
    second = broker.publish(stream, {"data": "test2"})
    assert broker.get_next(stream, consumer_group)[0] == first

    # Check Redis position key
    position_key = f"position:{stream}:{consumer_group}"
    position = broker.redis_instance.get(position_key)
    assert position is not None
    assert int(position) == 1  # Should be incremented

    # The next read continues from the stored position
    assert broker.get_next(stream, consumer_group)[0] == second
    assert int(broker.redis_instance.get(position_key)) == 2


@pytest.mark.redis
def test_redis_data_reset_clears_internal_state(broker):
    """Test Redis data reset clears both Redis and internal broker state"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Create some data, with two consumer groups on the stream
    broker.publish(stream, message)
    broker.get_next(stream, consumer_group)
    broker.get_next(stream, "another_group")

    # Verify data exists
    assert broker.redis_instance.llen(stream) == 1
    assert len(broker._consumer_groups) == 2

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
