import pytest


@pytest.mark.broker
def test_for_no_error_on_no_message(test_domain):
    message = test_domain.brokers["default"].get_next("test_stream")
    assert message is None


@pytest.mark.broker
def test_get_next_message(test_domain):
    stream = "test_stream"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    test_domain.brokers["default"].publish(stream, message1)
    test_domain.brokers["default"].publish(stream, message2)

    # Retrieve the first message
    retrieved_message = test_domain.brokers["default"].get_next(stream)
    assert retrieved_message[1] == message1

    # Retrieve the second message
    retrieved_message = test_domain.brokers["default"].get_next(stream)
    assert retrieved_message[1] == message2

    # No more messages, should return an empty dict
    retrieved_message = test_domain.brokers["default"].get_next(stream)
    assert retrieved_message is None
