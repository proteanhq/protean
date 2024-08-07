import asyncio

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.server import Engine

terms = []


def append_to_terms(term):
    global terms
    terms.append(term)


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        append_to_terms(data["foo"])


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
def clear_terms():
    yield

    global terms
    terms = []


@pytest.mark.broker_common
def test_processing_broker_messages(test_domain):
    test_domain.register(DummySubscriber, channel="test_channel")
    test_domain.init(traverse=False)

    channel = "test_channel"
    message1 = {"foo": "bar"}
    message2 = {"foo": "baz"}
    test_domain.brokers["default"].publish(channel, message1)
    test_domain.brokers["default"].publish(channel, message2)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    global terms
    assert len(terms) == 2
    assert terms[0] == "bar"
    assert terms[1] == "baz"


@pytest.mark.broker_common
def test_no_processing_when_shutting_down(test_domain):
    test_domain.register(DummySubscriber, channel="test_channel")
    test_domain.init(traverse=False)

    channel = "test_channel"
    message = {"foo": "bar"}
    test_domain.brokers["default"].publish(channel, message)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.shutting_down = True
    engine.run()

    global terms
    assert len(terms) == 0
