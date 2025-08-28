from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import Processing
from protean.utils.message import Message
from protean.utils.mixins import handle


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


def some_function():
    raise Exception("Some exception")


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        some_function()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value

    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.asyncio
async def test_that_exception_is_handled_but_engine_continues(test_domain, caplog):
    identifier = str(uuid4())
    user = User(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    user.raise_(
        Registered(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )
    message = Message.to_message(user._events[-1])

    engine = Engine(domain=test_domain, test_mode=True)

    await engine.handle_message(UserEventHandler, message)

    # Verify the engine did not shut down (change from previous behavior)
    assert not engine.shutting_down
    assert engine.exit_code == 0

    # But the error was still logged
    assert any(
        record.levelname == "ERROR" and "Error handling message" in record.message
        for record in caplog.records
    )


def test_exceptions_do_not_stop_processing(test_domain, caplog):
    identifier = str(uuid4())
    user = User(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    user.raise_(
        Registered(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    # Run with test_mode to avoid actual event loop execution
    engine = Engine(domain=test_domain, test_mode=True)

    # Since we can't easily test the full engine run without mocking,
    # we'll test that the message handling doesn't shut down the engine
    loop = engine.loop
    loop.run_until_complete(
        engine.handle_message(UserEventHandler, Message.to_message(user._events[-1]))
    )

    # Verify the engine did not shut down
    assert not engine.shutting_down
    assert engine.exit_code == 0

    # But the error was still logged
    assert any(
        record.levelname == "ERROR" and "Error handling message" in record.message
        for record in caplog.records
    )
