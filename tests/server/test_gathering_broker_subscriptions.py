import asyncio

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.server import Engine
from protean.utils import fqn


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        pass


@pytest.fixture(autouse=True)
def auto_set_and_close_loop():
    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield

    # Close the loop after the test
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)  # Explicitly unset the loop


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(DummySubscriber, channel="test_channel")
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    return Engine(test_domain, test_mode=True)


def test_broker_subscriptions(engine):
    assert len(engine._broker_subscriptions) == 1

    assert fqn(DummySubscriber) in engine._broker_subscriptions
