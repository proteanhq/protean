def test_publish_to_channel(test_domain):
    channel = "test_channel"
    message = {"foo": "bar"}

    test_domain.brokers["default"].publish(channel, message)

    # Verify message is stored
    assert test_domain.brokers["default"]._messages[channel] == [message]


def test_get_next_message(test_domain):
    channel = "test_channel"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    test_domain.brokers["default"].publish(channel, message1)
    test_domain.brokers["default"].publish(channel, message2)

    # Retrieve the first message
    retrieved_message = test_domain.brokers["default"].get_next(channel)
    assert retrieved_message == message1

    # Retrieve the second message
    retrieved_message = test_domain.brokers["default"].get_next(channel)
    assert retrieved_message == message2

    # No more messages, should return an empty dict
    retrieved_message = test_domain.brokers["default"].get_next(channel)
    assert retrieved_message is None


def test_data_reset(test_domain):
    channel1 = "test_channel1"
    channel2 = "test_channel2"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    test_domain.brokers["default"].publish(channel1, message1)
    test_domain.brokers["default"].publish(channel2, message2)

    # Reset the broker data
    test_domain.brokers["default"]._data_reset()

    # Verify all messages are cleared
    assert test_domain.brokers["default"]._messages[channel1] == []
    assert test_domain.brokers["default"]._messages[channel2] == []
    assert test_domain.brokers["default"]._messages == {
        "test_channel1": [],
        "test_channel2": [],
    }


def test_is_async_flag(test_domain):
    # Verify that the IS_ASYNC flag is set to False
    assert test_domain.brokers["default"].conn_info["IS_ASYNC"] is False
