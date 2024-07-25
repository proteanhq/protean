import asyncio
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier
from protean.server.engine import Engine
from protean.utils import EventProcessing
from protean.utils.mixins import handle

counter = 0


def count_up():
    global counter
    counter += 1


class User(BaseAggregate):
    user_id = Identifier(identifier=True)


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


class UserEventHandler(BaseEventHandler):
    @handle(UserLoggedIn)
    def count_users(self, event: UserLoggedIn) -> None:
        count_up()


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
    test_domain.config["event_processing"] = EventProcessing.ASYNC.value
    test_domain.register(User, stream_category="authentication")
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.register(UserEventHandler, stream_category="authentication")
    test_domain.init(traverse=False)


def test_processing_messages_on_start(test_domain):
    identifier = str(uuid4())
    user = User(user_id=identifier)
    user.raise_(UserLoggedIn(user_id=identifier))
    test_domain.repository_for(User).add(user)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    global counter
    assert counter == 1


def test_that_read_position_is_updated_after_engine_run(test_domain):
    identifier = str(uuid4())
    user = User(user_id=identifier)
    user.raise_(UserLoggedIn(user_id=identifier))
    test_domain.repository_for(User).add(user)

    messages = test_domain.event_store.store.read("authentication")
    assert len(messages) == 1

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    messages = test_domain.event_store.store.read("$all")
    assert len(messages) == 2


def test_processing_messages_from_beginning_the_first_time(test_domain):
    identifier = str(uuid4())
    user = User(user_id=identifier)
    user.raise_(UserLoggedIn(user_id=identifier))
    test_domain.repository_for(User).add(user)

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
