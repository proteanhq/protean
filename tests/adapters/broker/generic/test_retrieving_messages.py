import pytest


@pytest.mark.broker
def test_for_no_error_on_no_message(test_domain):
    message = test_domain.brokers["default"].get_next("test_channel")
    assert message is None


@pytest.mark.broker
def test_get_next_message(test_domain):
    channel = "test_channel"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    test_domain.brokers["default"].publish(channel, message1)
    test_domain.brokers["default"].publish(channel, message2)

    # Retrieve the first message
    retrieved_message = test_domain.brokers["default"].get_next(channel)
    assert retrieved_message[1] == message1

    # Retrieve the second message
    retrieved_message = test_domain.brokers["default"].get_next(channel)
    assert retrieved_message[1] == message2

    # No more messages, should return an empty dict
    retrieved_message = test_domain.brokers["default"].get_next(channel)
    assert retrieved_message is None
