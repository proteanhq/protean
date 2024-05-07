import asyncio

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventHandler, Engine, handle
from protean.fields import Identifier

counter = 0


def count_up():
    global counter
    counter += 1


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)

    class Meta:
        stream_name = "authentication"


class UserEventHandler(BaseEventHandler):
    @handle(UserLoggedIn)
    def count_users(self, event: UserLoggedIn) -> None:
        count_up()

    class Meta:
        stream_name = "authentication"


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


def test_processing_messages_on_start(test_domain):
    test_domain.register(UserLoggedIn)
    test_domain.register(UserEventHandler)

    identifier = str(uuid4())
    event = UserLoggedIn(user_id=identifier)
    test_domain.event_store.store.append(event)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    global counter
    assert counter == 1


def test_that_read_position_is_updated_after_engine_run(test_domain):
    test_domain.register(UserLoggedIn)
    test_domain.register(UserEventHandler)

    identifier = str(uuid4())
    event = UserLoggedIn(user_id=identifier)
    test_domain.event_store.store.append(event)

    messages = test_domain.event_store.store.read("authentication")
    assert len(messages) == 1

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    messages = test_domain.event_store.store.read("$all")
    assert len(messages) == 2


def test_processing_messages_from_beginning_the_first_time(test_domain):
    test_domain.register(UserLoggedIn)
    test_domain.register(UserEventHandler)

    identifier = str(uuid4())
    event = UserLoggedIn(user_id=identifier)
    test_domain.event_store.store.append(event)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    messages = test_domain.event_store.store.read("$all")
    assert len(messages) == 2

    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    messages = test_domain.event_store.store.read("$all")
    assert len(messages) == 2
