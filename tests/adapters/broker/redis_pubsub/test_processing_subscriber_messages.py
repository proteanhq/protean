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
def setup(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.config["message_processing"] = Processing.ASYNC.value
    test_domain.init(traverse=False)


@pytest.mark.redis
@pytest.mark.asyncio
async def test_handler_invocation(test_domain, broker):
    with test_domain.domain_context():
        stream = "test_stream"
        message = {"foo": "bar"}

        broker.publish(stream, message)

        engine = Engine(domain=test_domain, test_mode=True)
        await engine.handle_broker_message(DummySubscriber, message)

        global terms
        assert len(terms) == 1
        assert terms[0] == "bar"


@pytest.mark.redis
def test_processing_broker_messages(test_domain, broker):
    with test_domain.domain_context():
        stream = "test_stream"
        message1 = {"foo": "bar"}
        message2 = {"foo": "baz"}
        broker.publish(stream, message1)
        broker.publish(stream, message2)

        engine = Engine(domain=test_domain, test_mode=True)
        engine.run()

        global terms
        assert len(terms) == 2
        assert terms[0] == "bar"
        assert terms[1] == "baz"
