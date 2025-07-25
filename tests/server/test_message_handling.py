import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine

counter = 0


def count_up():
    global counter
    counter += 1


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        count_up()


class ExceptionSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        raise Exception("This is a dummy exception")


@pytest.fixture(autouse=True)
def set_message_processing_async(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value


@pytest.mark.asyncio
async def test_handler_invocation(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.init(traverse=False)

    stream = "test_stream"
    message = {"foo": "bar"}

    test_domain.brokers["default"].publish(stream, message)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_broker_message(DummySubscriber, message)

    global counter
    assert counter == 1


@pytest.mark.asyncio
async def test_handling_exception_raised_in_handler(test_domain, caplog):
    test_domain.register(ExceptionSubscriber, stream="test_stream")
    test_domain.init(traverse=False)

    stream = "test_stream"
    message = {"foo": "bar"}

    test_domain.brokers["default"].publish(stream, message)

    engine = Engine(domain=test_domain, test_mode=True)

    await engine.handle_broker_message(ExceptionSubscriber, message)

    assert any(
        record.levelname == "ERROR" and "Error handling message in " in record.message
        for record in caplog.records
    )

    assert not engine.shutting_down
    assert engine.exit_code == 0
