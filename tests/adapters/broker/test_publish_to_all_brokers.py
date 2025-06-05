import pytest


@pytest.fixture(autouse=True)
def setup(test_domain):
    test_domain.config["brokers"]["secondary"] = {"provider": "inline"}
    test_domain.init(traverse=False)


def test_publish_to_stream(test_domain):
    stream = "test_stream"
    message = {"foo": "bar"}

    test_domain.brokers.publish(stream, message)

    # Verify message is stored as tuple (identifier, message) in both brokers
    assert len(test_domain.brokers["default"]._messages[stream]) == 1
    assert len(test_domain.brokers["secondary"]._messages[stream]) == 1

    # Check default broker storage
    default_tuple = test_domain.brokers["default"]._messages[stream][0]
    assert isinstance(default_tuple, tuple)
    assert len(default_tuple) == 2
    assert isinstance(default_tuple[0], str)  # identifier
    assert default_tuple[1] == message  # original message

    # Check secondary broker storage
    secondary_tuple = test_domain.brokers["secondary"]._messages[stream][0]
    assert isinstance(secondary_tuple, tuple)
    assert len(secondary_tuple) == 2
    assert isinstance(secondary_tuple[0], str)  # identifier
    assert secondary_tuple[1] == message  # original message
