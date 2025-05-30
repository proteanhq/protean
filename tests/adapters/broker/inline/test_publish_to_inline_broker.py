def test_publish_to_channel(test_domain):
    channel = "test_channel"
    message = {"foo": "bar"}

    test_domain.brokers["default"].publish(channel, message)

    # Verify message is stored
    assert test_domain.brokers["default"]._messages[channel] == [message]
