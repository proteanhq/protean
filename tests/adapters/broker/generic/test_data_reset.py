import pytest


@pytest.mark.broker
def test_data_reset(test_domain):
    channel1 = "test_channel1"
    channel2 = "test_channel2"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    test_domain.brokers["default"].publish(channel1, message1)
    test_domain.brokers["default"].publish(channel2, message2)

    # Reset the broker data
    test_domain.brokers["default"]._data_reset()

    assert test_domain.brokers["default"].get_next(channel1) is None
    assert test_domain.brokers["default"].get_next(channel2) is None
