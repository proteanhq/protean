import pytest

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
error_handler_error_counter = 0


# Reset counter before each test
@pytest.fixture(autouse=True)
def reset_counters():
    global error_handler_counter, error_handler_error_counter
    error_handler_counter = 0
    error_handler_error_counter = 0


class User(BaseAggregate):
    email = String()
    name = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


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


class ErrorInErrorHandlerEventHandler(BaseEventHandler):
    """Event handler with a handle_error method that raises an exception"""

    @handle(Registered)
    def process_registered(self, event):
        # Always throw an exception in the handler
        raise Exception("Intentional test exception")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_error_counter
        error_handler_error_counter += 1
        # This exception should be caught by the Subscription
        raise Exception("Error in error handler")


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


class ErrorInErrorHandlerSubscriber(BaseSubscriber):
    """Subscriber with a handle_error method that raises an exception"""

    def __call__(self, data):
        # Always throw an exception
        raise Exception("Intentional test exception")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_error_counter
        error_handler_error_counter += 1
        # This exception should be caught by the BrokerSubscription
        raise Exception("Error in error handler")


@pytest.fixture
def test_domain_setup(test_domain):
    # Set up the domain with our test classes
    test_domain.config["event_processing"] = Processing.ASYNC.value

    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ErrorHandlerEventHandler, part_of=User)
    test_domain.register(ErrorInErrorHandlerEventHandler, part_of=User)
    test_domain.register(ErrorHandlerSubscriber, stream="test_stream")
    test_domain.register(ErrorInErrorHandlerSubscriber, stream="error_stream")

    test_domain.init(traverse=False)
    return test_domain


@pytest.mark.asyncio
async def test_event_handler_error_handling(test_domain_setup, caplog):
    """Test that error handlers are called when exceptions occur in event handlers"""
    # Create test data
    engine = Engine(domain=test_domain_setup, test_mode=True)

    # Create and persist a user
    user_id = "test-id-1"
    user = User(id=user_id, email="test1@example.com", name="Test User 1")
    user.raise_(Registered(id=user_id, email="test1@example.com", name="Test User 1"))

    # Directly call handle_message for both event handlers to test error handling
    # For normal handler that has error handler
    message = Message.from_domain_object(user._events[-1])

    # Test the handler with normal error handling
    await engine.handle_message(ErrorHandlerEventHandler, message)
    assert error_handler_counter == 1
    assert "Error handling message" in caplog.text
    assert "Intentional test exception" in caplog.text

    # Test handler with exception in error handler
    await engine.handle_message(ErrorInErrorHandlerEventHandler, message)
    assert error_handler_error_counter == 1
    assert "Error in error handler" in caplog.text

    # Verify engine is still running
    assert not engine.shutting_down


@pytest.mark.asyncio
async def test_subscriber_error_handling(test_domain_setup, caplog):
    """Test that error handlers are called when exceptions occur in subscribers"""
    # Create test data
    engine = Engine(domain=test_domain_setup, test_mode=True)

    # Create test message
    test_message = {"data": "test"}

    # Test normal subscriber with error handler
    await engine.handle_broker_message(ErrorHandlerSubscriber, test_message)
    assert error_handler_counter == 1
    assert "Error handling message in" in caplog.text
    assert "Intentional test exception" in caplog.text

    # Test subscriber with exception in error handler
    await engine.handle_broker_message(ErrorInErrorHandlerSubscriber, test_message)
    assert error_handler_error_counter == 1
    assert "Error in error handler" in caplog.text

    # Verify engine is still running
    assert not engine.shutting_down


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
