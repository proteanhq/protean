import pytest

# Tests for BaseManualBroker-specific ack functionality with in-flight tracking and operation states


@pytest.mark.manual_broker
def test_ack_removes_from_in_flight_tracking(broker):
    """Test that acknowledging a message removes it from in-flight tracking (BaseManualBroker specific)"""
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
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 2

    # Acknowledge first message
    ack_result = broker.ack(stream, id1, consumer_group)
    assert ack_result is True

    # Check that in-flight count decreased
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 1


@pytest.mark.manual_broker
def test_ack_cleans_up_message_ownership(broker):
    """Test that acknowledging a message cleans up ownership tracking (BaseManualBroker specific)"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify ownership is tracked (implementation-specific check)
    if hasattr(broker, "_message_ownership"):
        assert identifier in broker._message_ownership
        assert consumer_group in broker._message_ownership[identifier]

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Verify ownership is cleaned up
    if hasattr(broker, "_message_ownership"):
        assert identifier not in broker._message_ownership


@pytest.mark.manual_broker
def test_ack_message_already_acknowledged_idempotent(broker):
    """Test ack idempotency when message already acknowledged (BaseManualBroker specific)"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Acknowledge once
    result1 = broker.ack(stream, identifier, consumer_group)
    assert result1 is True

    # Try to acknowledge again - should be idempotent
    result2 = broker.ack(stream, identifier, consumer_group)
    assert result2 is False
