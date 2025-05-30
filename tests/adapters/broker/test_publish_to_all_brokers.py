import pytest


@pytest.fixture(autouse=True)
def setup(test_domain):
    test_domain.config["brokers"]["secondary"] = {"provider": "inline"}
    test_domain.init(traverse=False)


def test_publish_to_channel(test_domain):
    channel = "test_channel"
    message = {"foo": "bar"}

    test_domain.brokers.publish(channel, message)

    # Verify message is stored
    assert test_domain.brokers["default"]._messages[channel] == [message]
    assert test_domain.brokers["secondary"]._messages[channel] == [message]
