import pytest

from protean.core.subscriber import BaseSubscriber
from protean.utils import Processing

counter = 0


def count_up():
    global counter
    counter += 1


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        count_up()


@pytest.mark.broker
def test_subscriber_sync_invocation(test_domain):
    test_domain.config["message_processing"] = Processing.SYNC.value

    test_domain.register(DummySubscriber, channel="test_channel")
    test_domain.init(traverse=False)

    channel = "test_channel"
    message = {"foo": "bar"}

    test_domain.brokers["default"].publish(channel, message)

    global counter
    assert counter == 1
