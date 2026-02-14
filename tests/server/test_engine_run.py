import asyncio
import logging
from unittest.mock import patch
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.server.engine import Engine
from protean.utils import Processing
from protean.utils.mixins import handle

counter = 0


def count_up():
    global counter
    counter += 1


class User(BaseAggregate):
    user_id: str | None = None


class UserLoggedIn(BaseEvent):
    user_id: str | None = None


class UserEventHandler(BaseEventHandler):
    @handle(UserLoggedIn)
    def count_users(self, event: UserLoggedIn) -> None:
        count_up()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
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


def test_engine_run_non_test_mode(test_domain, caplog):
    """Test that engine runs in non-test mode with run_forever."""
    engine = Engine(domain=test_domain, test_mode=False)

    with patch.object(engine.loop, "run_forever") as mock_run_forever:
        with caplog.at_level(logging.INFO, logger="protean.server.engine"):
            engine.run()

    mock_run_forever.assert_called_once()
    assert any(
        "Engine started successfully" in record.message for record in caplog.records
    )


def test_engine_test_mode_cancels_long_running_tasks(test_domain, caplog):
    """Test that test mode cancels tasks still running after 3 cycles."""
    engine = Engine(domain=test_domain, test_mode=True)

    # Replace the subscriptions with a mock that has a long-running start()
    async def long_running_start():
        """A start() coroutine that blocks for longer than the 3 test cycles."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    class FakeSubscription:
        async def start(self):
            await long_running_start()

        async def shutdown(self):
            pass

    # Inject a fake subscription so the engine has tasks to manage
    engine._subscriptions = {"fake-handler": FakeSubscription()}

    with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
        engine.run()

    # Verify all 3 cycles ran (task was still running through all cycles)
    cycle_msgs = [r.message for r in caplog.records if "Test mode cycle" in r.message]
    assert len(cycle_msgs) == 3
