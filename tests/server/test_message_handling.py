import pytest

from protean.core.subscriber import BaseSubscriber
from protean.server import Engine

counter = 0


def count_up():
    global counter
    counter += 1


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        count_up()


@pytest.mark.asyncio
async def test_handler_invocation(test_domain):
    test_domain.register(DummySubscriber, channel="test_channel")
    test_domain.init(traverse=False)

    channel = "test_channel"
    message = {"foo": "bar"}

    test_domain.brokers["default"].publish(channel, message)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_broker_message(DummySubscriber, message)

    global counter
    assert counter == 1
