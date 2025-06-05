import pytest


@pytest.mark.broker
def test_data_reset(test_domain):
    stream1 = "test_stream1"
    stream2 = "test_stream2"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    test_domain.brokers["default"].publish(stream1, message1)
    test_domain.brokers["default"].publish(stream2, message2)

    # Reset the broker data
    test_domain.brokers["default"]._data_reset()

    assert test_domain.brokers["default"].get_next(stream1) is None
    assert test_domain.brokers["default"].get_next(stream2) is None
