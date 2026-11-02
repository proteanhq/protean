import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import Processing
from protean.utils.eventing import Message
from protean.utils.mixins import handle

# Counter for tracking method calls
error_handler_counter = 0


# Reset counter before each test
@pytest.fixture(autouse=True)
def reset_counters():
    global error_handler_counter
    error_handler_counter = 0


class Registered(BaseEvent):
    id: Identifier()
    email: String()
    name: String()


class User(BaseAggregate):
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


# Test Event Handlers
class ErrorHandlerEventHandler(BaseEventHandler):
    """Event handler with a handle_error method that succeeds"""

    @handle(Registered)
    def process_registered(self, event):
        # Always throw an exception in the handler
        raise Exception("Intentional test exception")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


# Subscriber classes
class ErrorHandlerSubscriber(BaseSubscriber):
    """Subscriber with a handle_error method that succeeds"""

    def __call__(self, data):
        # Always throw an exception
        raise Exception("Intentional test exception")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


@pytest.fixture
def test_domain_setup(test_domain):
    # Set up the domain with our test classes
    test_domain.config["event_processing"] = Processing.ASYNC.value

    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ErrorHandlerEventHandler, part_of=User)
    test_domain.register(ErrorHandlerSubscriber, stream="test_stream")

    test_domain.init(traverse=False)
    return test_domain


@pytest.mark.asyncio
async def test_handle_message_during_shutdown(test_domain_setup):
    """Test that handle_message returns False when the engine is shutting down"""
    # Create test data
    engine = Engine(domain=test_domain_setup, test_mode=True)

    # Create a user and event
    user_id = "test-id-shutdown"
    user = User(id=user_id, email="shutdown@example.com", name="Shutdown Test")
    user.raise_(
        Registered(id=user_id, email="shutdown@example.com", name="Shutdown Test")
    )
    message = Message.from_domain_object(user._events[-1])

    # Set the shutting_down flag
    engine.shutting_down = True

    # Verify handle_message returns False when engine is shutting down
    result = await engine.handle_message(ErrorHandlerEventHandler, message)
    assert result is False

    # Verify error handler was not called (counter unchanged)
    assert error_handler_counter == 0

    # Test handle_broker_message also returns False during shutdown
    broker_result = await engine.handle_broker_message(
        ErrorHandlerSubscriber, {"data": "test"}
    )
    assert broker_result is False

    # Verify error handler was not called (counter unchanged)
    assert error_handler_counter == 0


@pytest.mark.asyncio
async def test_handle_message_while_draining_still_runs(test_domain_setup):
    """handle_message is NOT gated on draining: an in-flight message runs.

    Unlike shutting_down, draining must let already-dispatched work finish, so
    the handler is invoked (here it raises and its handle_error runs, bumping the
    counter). If draining rejected at the guard, the handler would never run and
    the counter would stay 0.
    """
    engine = Engine(domain=test_domain_setup, test_mode=True)
    engine.draining = True

    user_id = "test-id-draining"
    user = User(id=user_id, email="draining@example.com", name="Draining Test")
    user.raise_(
        Registered(id=user_id, email="draining@example.com", name="Draining Test")
    )
    message = Message.from_domain_object(user._events[-1])

    await engine.handle_message(ErrorHandlerEventHandler, message)
    assert error_handler_counter == 1

    # handle_broker_message likewise runs its subscriber while draining.
    await engine.handle_broker_message(ErrorHandlerSubscriber, {"data": "test"})
    assert error_handler_counter == 2
