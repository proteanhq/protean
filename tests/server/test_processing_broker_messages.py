import asyncio

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine

terms = []


def append_to_terms(term):
    global terms
    terms.append(term)


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        append_to_terms(data["foo"])


@pytest.fixture(autouse=True)
def clear_terms():
    yield

    global terms
    terms = []


@pytest.fixture(autouse=True)
def set_message_processing_async(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value


def test_processing_broker_messages(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.init(traverse=False)

    stream = "test_stream"
    message1 = {"foo": "bar"}
    message2 = {"foo": "baz"}
    test_domain.brokers["default"].publish(stream, message1)
    test_domain.brokers["default"].publish(stream, message2)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    global terms
    assert len(terms) == 2
    assert terms[0] == "bar"
    assert terms[1] == "baz"


def test_no_processing_when_shutting_down(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.init(traverse=False)

    stream = "test_stream"
    message = {"foo": "bar"}
    test_domain.brokers["default"].publish(stream, message)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.shutting_down = True
    engine.run()

    global terms
    assert len(terms) == 0
