from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

# Track invocations for testing
event_counter1 = 0
event_counter2 = 0


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    name = String()


class LoginCommand(BaseCommand):
    user_id = Identifier()
    name = String()
    password = String()


class UserRegisteredEvent(BaseEvent):
    user_id = Identifier()
    name = String()


class UserCommandHandler(BaseCommandHandler):
    @handle(LoginCommand)
    def login(self, command):
        user = User(user_id=command.user_id, name="Test User")
        user.raise_(UserRegisteredEvent(user_id=command.user_id, name=command.name))

        current_domain.repository_for(User).add(user)

        # Return a value (like a token) that should be passed back when sync processing
        return {"token": f"token-{command.user_id}"}


class UserEventHandler1(BaseEventHandler):
    @handle(UserRegisteredEvent)
    def on_user_registered(self, event):
        global event_counter1
        event_counter1 += 1
        # Return a value that should NOT be passed back
        return "This should be ignored"


class UserEventHandler2(BaseEventHandler):
    @handle(UserRegisteredEvent)
    def on_user_registered_again(self, event):
        global event_counter2
        event_counter2 += 1
        # Return a value that should NOT be passed back
        return "This too should be ignored"


@pytest.fixture(autouse=True)
def reset_counters():
    """Reset all counters before each test."""
    global event_counter1, event_counter2
    event_counter1 = 0
    event_counter2 = 0
    yield


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(LoginCommand, part_of=User)
    test_domain.register(UserRegisteredEvent, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(UserEventHandler1, part_of=User)
    test_domain.register(UserEventHandler2, part_of=User)
    test_domain.init(traverse=False)


def test_command_handler_returns_value_when_processed_synchronously(test_domain):
    """Test that command handlers can return values when processed synchronously."""
    user_id = str(uuid4())

    # Process command synchronously
    result = test_domain.process(
        LoginCommand(user_id=user_id, password="secret"), asynchronous=False
    )

    # Verify the handler was called
    retrieved_user = test_domain.repository_for(User).get(user_id)
    assert retrieved_user is not None
    assert retrieved_user.user_id == user_id

    # Verify the handler's return value was returned by process
    assert result == {"token": f"token-{user_id}"}


def test_command_handler_returns_position_when_processed_asynchronously(test_domain):
    """Test that command handlers return None when processed asynchronously."""
    user_id = str(uuid4())

    test_domain.config["command_processing"] = Processing.ASYNC.value

    result = test_domain.process(
        LoginCommand(user_id=user_id, password="secret"), asynchronous=True
    )

    assert result == 0


def test_event_handlers_are_all_executed_and_return_nothing(test_domain):
    """Test that all event handlers for an event are executed and nothing is returned."""
    user_id = str(uuid4())

    test_domain.config["command_processing"] = Processing.SYNC.value
    test_domain.config["event_processing"] = Processing.SYNC.value

    # Process command synchronously
    result = test_domain.process(LoginCommand(user_id=user_id, password="secret"))

    assert result == {"token": f"token-{user_id}"}

    # Verify both handlers were executed synchronously
    assert event_counter1 == 1
    assert event_counter2 == 1


def test_command_and_event_handling_integration(test_domain):
    """Test that command handlers return values but event handlers don't in an integration flow."""
    user_id = str(uuid4())

    test_domain.config["command_processing"] = Processing.SYNC.value
    test_domain.config["event_processing"] = Processing.ASYNC.value

    # 1. Process command synchronously and get token
    result = test_domain.process(
        LoginCommand(user_id=user_id, password="secret"), asynchronous=False
    )

    # Verify command handler was called and returned the token
    assert result == {"token": f"token-{user_id}"}

    # Verify both event handlers were not executed
    assert event_counter1 == 0
    assert event_counter2 == 0
