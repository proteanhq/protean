import time

import pytest


@pytest.mark.broker
def test_dlq_message_inspection(broker):
    """Test that DLQ messages can be inspected"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar", "id": 123}

    # Configure broker for DLQ testing
    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack the message until it goes to DLQ
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True
            if i == 0:
                time.sleep(0.02)

    # Get messages for specific stream
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 1

    dlq_entry = dlq_messages[stream][0]
    assert dlq_entry[0] == identifier
    assert dlq_entry[1] == message
    assert dlq_entry[2] == "max_retries_exceeded"

    # Get all DLQ messages for consumer group
    all_dlq_messages = broker.get_dlq_messages(consumer_group)
    assert stream in all_dlq_messages
    assert len(all_dlq_messages[stream]) == 1


@pytest.mark.broker
def test_dlq_message_reprocessing(broker):
    """Test that DLQ messages can be moved back for reprocessing"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar", "id": 456}

    # Configure broker for DLQ testing
    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Publish a message
    identifier = broker.publish(stream, message)

    # Nack the message until it goes to DLQ
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True
            if i == 0:
                time.sleep(0.02)

    # Verify message is in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 1

    # Reprocess the message from DLQ
    reprocess_result = broker.reprocess_dlq_message(identifier, consumer_group, stream)
    assert reprocess_result is True

    # Verify DLQ is now empty
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) == 0

    # Verify message is available for processing again
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier
    assert retrieved_message[1] == message


@pytest.mark.broker
def test_dlq_multiple_messages(broker):
    """Test DLQ with multiple failed messages"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    messages = [{"id": i, "data": f"message_{i}"} for i in range(3)]

    # Configure broker for DLQ testing
    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Publish multiple messages
    identifiers = []
    for message in messages:
        identifier = broker.publish(stream, message)
        identifiers.append(identifier)

    # Nack all messages until they go to DLQ
    for identifier in identifiers:
        for i in range(2):
            retrieved_message = broker.get_next(stream, consumer_group)
            if retrieved_message and retrieved_message[0] == identifier:
                nack_result = broker.nack(stream, identifier, consumer_group)
                assert nack_result is True
                if i == 0:
                    time.sleep(0.02)

    # Check all messages are in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 3

    dlq_identifiers = [entry[0] for entry in dlq_messages[stream]]
    for identifier in identifiers:
        assert identifier in dlq_identifiers


@pytest.mark.broker
def test_dlq_cross_consumer_group_isolation(broker):
    """Test that DLQ messages are isolated between consumer groups"""
    stream = "test_stream"
    consumer_group_1 = "group_1"
    consumer_group_2 = "group_2"
    message1 = {"group": 1, "data": "message_1"}
    message2 = {"group": 2, "data": "message_2"}

    # Configure broker for DLQ testing
    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Publish messages
    id1 = broker.publish(stream, message1)
    broker.publish(stream, message2)

    # Group 1 processes and nacks first message
    msg1 = broker.get_next(stream, consumer_group_1)
    assert msg1 is not None
    assert msg1[0] == id1

    for i in range(2):
        if i > 0:
            msg1 = broker.get_next(stream, consumer_group_1)
        if msg1:
            nack_result = broker.nack(stream, id1, consumer_group_1)
            assert nack_result is True
            if i == 0:
                time.sleep(0.02)

    # Group 2 processes and nacks its first message (which happens to be the same as group 1's first message)
    msg2 = broker.get_next(stream, consumer_group_2)
    assert msg2 is not None
    # Each consumer group gets the first message independently
    message_id_for_group2 = msg2[
        0
    ]  # Could be id1 since consumer groups read independently
    assert message_id_for_group2 == id1

    for i in range(2):
        if i > 0:
            msg2 = broker.get_next(stream, consumer_group_2)
        if msg2:
            nack_result = broker.nack(stream, message_id_for_group2, consumer_group_2)
            assert nack_result is True
            if i == 0:
                time.sleep(0.02)

    # Check DLQ isolation
    dlq_messages_1 = broker.get_dlq_messages(consumer_group_1, stream)
    dlq_messages_2 = broker.get_dlq_messages(consumer_group_2, stream)

    # Each group should have only its own message in DLQ
    if stream in dlq_messages_1:
        assert len(dlq_messages_1[stream]) == 1
        assert dlq_messages_1[stream][0][0] == id1

    if stream in dlq_messages_2:
        assert len(dlq_messages_2[stream]) == 1
        assert dlq_messages_2[stream][0][0] == message_id_for_group2


@pytest.mark.broker
def test_dlq_info_tracking(broker):
    """Test that DLQ message counts are tracked in broker info"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker for DLQ testing
    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Publish a message
    identifier = broker.publish(stream, message)

    # Check initial info
    info = broker.info()
    initial_dlq_count = 0

    # Nack the message until it goes to DLQ
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is True
            if i == 0:
                time.sleep(0.02)

    # Check that DLQ count increased
    info = broker.info()
    dlq_info = info["consumer_groups"][consumer_group].get("dlq_messages", {})
    final_dlq_count = dlq_info.get(stream, 0)

    assert final_dlq_count == initial_dlq_count + 1


@pytest.mark.broker
def test_get_dlq_messages_no_messages(broker):
    """Test getting DLQ messages when none exist"""
    consumer_group = "test_consumer_group"
    stream = "empty_stream"

    # Try to get DLQ messages from empty stream
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 0


@pytest.mark.broker
def test_get_dlq_messages_specific_stream(broker):
    """Test getting DLQ messages for specific stream"""
    consumer_group = "test_consumer_group"
    stream1 = "stream1"
    stream2 = "stream2"
    message = {"data": "test"}

    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Add message to DLQ in stream1 by publishing and nacking
    identifier = broker.publish(stream1, message)

    # Nack until it goes to DLQ
    for i in range(2):
        retrieved_message = broker.get_next(stream1, consumer_group)
        if retrieved_message:
            broker.nack(stream1, identifier, consumer_group)
            if i == 0:
                time.sleep(0.02)

    # Get DLQ messages for specific stream
    dlq_messages = broker.get_dlq_messages(consumer_group, stream1)
    assert stream1 in dlq_messages
    assert len(dlq_messages[stream1]) == 1
    # stream2 should not be in the result
    assert stream2 not in dlq_messages


@pytest.mark.broker
def test_get_dlq_messages_all_streams(broker):
    """Test getting DLQ messages for all streams"""
    consumer_group = "test_consumer_group"
    stream1 = "stream1"
    stream2 = "stream2"
    message1 = {"data": "test1"}
    message2 = {"data": "test2"}

    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = True

    # Add messages to DLQ in both streams
    id1 = broker.publish(stream1, message1)
    id2 = broker.publish(stream2, message2)

    # Nack messages until they go to DLQ
    for stream, identifier in [(stream1, id1), (stream2, id2)]:
        for i in range(2):
            retrieved_message = broker.get_next(stream, consumer_group)
            if retrieved_message:
                broker.nack(stream, identifier, consumer_group)
                if i == 0:
                    time.sleep(0.02)

    # Get all DLQ messages
    dlq_messages = broker.get_dlq_messages(consumer_group)
    assert stream1 in dlq_messages
    assert stream2 in dlq_messages
    assert len(dlq_messages[stream1]) == 1
    assert len(dlq_messages[stream2]) == 1


@pytest.mark.broker
def test_reprocess_dlq_message_not_found(broker):
    """Test DLQ reprocessing when message not found"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "non-existent-id"

    result = broker.reprocess_dlq_message(identifier, consumer_group, stream)
    assert result is False


@pytest.mark.broker
def test_max_retries_exceeded_dlq_disabled(broker):
    """Test max retries exceeded with DLQ disabled"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    broker._retry_delay = 0.01
    broker._max_retries = 1
    broker._enable_dlq = False  # Disable DLQ

    # Publish and get message
    identifier = broker.publish(stream, message)

    # Nack until max retries exceeded
    for i in range(2):
        retrieved_message = broker.get_next(stream, consumer_group)
        if retrieved_message:
            result = broker.nack(stream, identifier, consumer_group)
            assert result is True  # Should succeed but discard message
            if i == 0:
                time.sleep(0.02)

    # Message should be discarded, not in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    if stream in dlq_messages:
        assert len(dlq_messages[stream]) == 0
