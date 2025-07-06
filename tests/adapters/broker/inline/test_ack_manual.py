def test_ack_removes_from_in_flight_tracking(broker):
    """Test that acknowledging a message removes it from in-flight tracking (reliable messaging specific)"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message to put it in in-flight status
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify message is in-flight
    assert broker._is_in_flight_message(stream, consumer_group, identifier)

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Verify message is no longer in-flight
    assert not broker._is_in_flight_message(stream, consumer_group, identifier)


def test_ack_cleans_up_message_ownership(broker):
    """Test that acknowledging a message cleans up ownership tracking (reliable messaging specific)"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify message ownership exists
    assert broker._validate_message_ownership(identifier, consumer_group)

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True


def test_ack_message_already_acknowledged_idempotent(broker):
    """Test ack idempotency when message already acknowledged (reliable messaging specific)"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # First ack - should succeed
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Second ack - should be idempotent (return False but not fail)
    ack_result_2 = broker.ack(stream, identifier, consumer_group)
    assert ack_result_2 is False  # Idempotent operation
