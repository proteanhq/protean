import pytest

from protean.core.subscriber import BaseSubscriber
from protean.exceptions import ConfigurationError


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        print("Received data: ", data)


def test_that_registered_subscribers_are_initialized(test_domain):
    test_domain.register(DummySubscriber, stream="person_added")
    test_domain.init(traverse=False)

    assert "person_added" in test_domain.brokers["default"]._subscribers
    assert (
        DummySubscriber in test_domain.brokers["default"]._subscribers["person_added"]
    )


def test_that_subscribers_with_unknown_brokers_cannot_be_initialized(test_domain):
    test_domain.register(DummySubscriber, stream="person_added", broker="unknown")

    with pytest.raises(ConfigurationError) as exc:
        test_domain.init(traverse=False)

    assert "Broker `unknown` has not been configured." in str(exc.value)

    # Reset the broker after test
    DummySubscriber.meta_.broker = "default"
