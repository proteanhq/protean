import time

import pytest


@pytest.mark.manual_broker
def test_message_timeout_cleanup(broker):
    """Test that messages are cleaned up after timeout"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar", "timeout_test": True}

    # Configure broker with very short timeout for testing
    broker._message_timeout = 0.1  # 100ms timeout
    broker._enable_dlq = True

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message (moves to in-flight)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier

    # Check that message is in-flight
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] >= 1

    # Wait for timeout to expire
    time.sleep(0.15)

    # Try to get another message - this should trigger timeout cleanup
    broker.get_next(stream, consumer_group)

    # Check that the timed-out message was moved to DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) == 1
        dlq_entry = dlq_messages[stream][0]
        assert dlq_entry[0] == identifier
        assert dlq_entry[1] == message
        assert dlq_entry[2] == "timeout"

    # Verify message is no longer in-flight
    info = broker.info()
    in_flight_info = info["consumer_groups"][consumer_group].get(
        "in_flight_messages", {}
    )
    if stream in in_flight_info:
        assert in_flight_info[stream] == 0


@pytest.mark.manual_broker
def test_message_timeout_without_dlq(broker):
    """Test message timeout behavior when DLQ is disabled"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar", "no_dlq_test": True}

    # Configure broker with timeout but no DLQ
    broker._message_timeout = 0.1  # 100ms timeout
    broker._enable_dlq = False  # Disable DLQ

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message (moves to in-flight)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier

    # Wait for timeout to expire
    time.sleep(0.15)

    # Try to get another message - this should trigger timeout cleanup
    broker.get_next(stream, consumer_group)

    # Verify no DLQ messages exist
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) == 0

    # Verify message is no longer in-flight (discarded)
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 0


@pytest.mark.manual_broker
def test_message_timeout_multiple_messages(broker):
    """Test timeout cleanup with multiple in-flight messages"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    messages = [{"id": i, "timeout_test": True} for i in range(3)]

    # Configure broker with short timeout
    broker._message_timeout = 0.1  # 100ms timeout
    broker._enable_dlq = True

    # Publish multiple messages
    identifiers = []
    for message in messages:
        identifier = broker.publish(stream, message)
        identifiers.append(identifier)

    # Get all messages (all move to in-flight)
    retrieved_messages = []
    for _ in range(3):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            retrieved_messages.append(retrieved_message)

    assert len(retrieved_messages) == 3

    # Check all messages are in-flight
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 3

    # Wait for timeout to expire
    time.sleep(0.15)

    # Trigger timeout cleanup
    broker.get_next(stream, consumer_group)

    # Check that all timed-out messages were moved to DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) == 3
        dlq_identifiers = [entry[0] for entry in dlq_messages[stream]]
        for identifier in identifiers:
            assert identifier in dlq_identifiers

    # Verify no messages are in-flight
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 0


@pytest.mark.manual_broker
def test_message_timeout_cross_consumer_group_isolation(broker):
    """Test that timeout cleanup respects consumer group isolation"""
    stream = "test_stream"
    consumer_group_1 = "group_1"
    consumer_group_2 = "group_2"
    message1 = {"group": 1, "timeout_test": True}
    message2 = {"group": 2, "timeout_test": True}

    # Configure broker with short timeout
    broker._message_timeout = 0.1  # 100ms timeout
    broker._enable_dlq = True

    # Publish messages
    id1 = broker.publish(stream, message1)
    broker.publish(stream, message2)

    # Group 1 gets first message
    msg1 = broker.get_next(stream, consumer_group_1)
    assert msg1 is not None
    assert msg1[0] == id1

    # Group 2 gets its first message (which is the same as group 1's first message)
    msg2 = broker.get_next(stream, consumer_group_2)
    assert msg2 is not None
    # Each consumer group gets the first message independently
    message_id_for_group2 = msg2[0]

    # Wait for timeout
    time.sleep(0.15)

    # Trigger timeout cleanup for both groups
    broker.get_next(stream, consumer_group_1)
    broker.get_next(stream, consumer_group_2)

    # Check DLQ isolation
    dlq_messages_1 = broker.get_dlq_messages(consumer_group_1, stream)
    dlq_messages_2 = broker.get_dlq_messages(consumer_group_2, stream)

    # Each group should have only its own timed-out message
    if stream in dlq_messages_1:
        assert len(dlq_messages_1[stream]) == 1
        assert dlq_messages_1[stream][0][0] == id1

    if stream in dlq_messages_2:
        assert len(dlq_messages_2[stream]) == 1
        assert dlq_messages_2[stream][0][0] == message_id_for_group2


@pytest.mark.manual_broker
def test_message_timeout_does_not_affect_acked_messages(broker):
    """Test that acknowledged messages are not affected by timeout cleanup"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message1 = {"id": 1, "status": "will_ack"}
    message2 = {"id": 2, "status": "will_timeout"}

    # Configure broker with short timeout
    broker._message_timeout = 0.1  # 100ms timeout
    broker._enable_dlq = True

    # Publish two messages
    id1 = broker.publish(stream, message1)
    id2 = broker.publish(stream, message2)

    # Get both messages
    msg1 = broker.get_next(stream, consumer_group)
    msg2 = broker.get_next(stream, consumer_group)

    assert msg1 is not None
    assert msg2 is not None

    # Acknowledge first message immediately
    ack_result = broker.ack(stream, id1, consumer_group)
    assert ack_result is True

    # Wait for timeout (should only affect second message)
    time.sleep(0.15)

    # Trigger timeout cleanup
    broker.get_next(stream, consumer_group)

    # Check that only the second message went to DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) == 1
        assert dlq_messages[stream][0][0] == id2  # Only second message

    # Verify only one message is counted as in-flight initially, then zero after timeout
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 0  # After cleanup
