from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import Processing
from protean.utils.eventing import Message
from protean.utils.mixins import handle

# Counters for verifying method calls
handler_counter = 0
error_handler_counter = 0
error_in_error_handler_counter = 0
broker_handler_counter = 0
broker_error_handler_counter = 0


@pytest.fixture(autouse=True)
def reset_counters():
    """Reset all counters before each test"""
    global handler_counter, error_handler_counter, error_in_error_handler_counter
    global broker_handler_counter, broker_error_handler_counter

    handler_counter = 0
    error_handler_counter = 0
    error_in_error_handler_counter = 0
    broker_handler_counter = 0
    broker_error_handler_counter = 0


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Register(BaseCommand):
    email = String()
    name = String()
    password_hash = String()


class NormalEventHandler(BaseEventHandler):
    """Handler that doesn't throw exceptions"""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter
        handler_counter += 1


class ErrorEventHandler(BaseEventHandler):
    """Handler that raises an exception and has a handle_error method"""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter
        handler_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


class ErrorInErrorHandlerEventHandler(BaseEventHandler):
    """Handler that raises an exception in both the handler and handle_error"""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter
        handler_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_in_error_handler_counter
        error_in_error_handler_counter += 1
        raise Exception("Error in error handler")


class NormalCommandHandler(BaseCommandHandler):
    """Command handler that doesn't throw exceptions"""

    @handle(Register)
    def handle_register(self, command):
        global handler_counter
        handler_counter += 1


class ErrorCommandHandler(BaseCommandHandler):
    """Command handler that raises an exception and has a handle_error method"""

    @handle(Register)
    def handle_register(self, command):
        global handler_counter
        handler_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


class ErrorInErrorHandlerCommandHandler(BaseCommandHandler):
    """Command handler that raises an exception in both the handler and handle_error"""

    @handle(Register)
    def handle_register(self, command):
        global handler_counter
        handler_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_in_error_handler_counter
        error_in_error_handler_counter += 1
        raise Exception("Error in error handler")


class NormalSubscriber(BaseSubscriber):
    """Subscriber that doesn't throw exceptions"""

    def __call__(self, data):
        global broker_handler_counter
        broker_handler_counter += 1


class ErrorSubscriber(BaseSubscriber):
    """Subscriber that raises an exception and has a handle_error method"""

    def __call__(self, data):
        global broker_handler_counter
        broker_handler_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global broker_error_handler_counter
        broker_error_handler_counter += 1


class ErrorInErrorHandlerSubscriber(BaseSubscriber):
    """Subscriber that raises an exception in both __call__ and handle_error"""

    def __call__(self, data):
        global broker_handler_counter
        broker_handler_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global broker_error_handler_counter
        broker_error_handler_counter += 1
        raise Exception("Error in error handler")


@pytest.fixture(autouse=True)
def register(test_domain):
    """Setup domain with all required handlers"""
    # Configure for async processing
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.config["command_processing"] = Processing.ASYNC.value

    # Register elements
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Register, part_of=User)

    # Register handlers
    test_domain.register(NormalEventHandler, part_of=User)
    test_domain.register(ErrorEventHandler, part_of=User)
    test_domain.register(ErrorInErrorHandlerEventHandler, part_of=User)
    test_domain.register(NormalCommandHandler, part_of=User)
    test_domain.register(ErrorCommandHandler, part_of=User)
    test_domain.register(ErrorInErrorHandlerCommandHandler, part_of=User)

    # Register subscribers
    test_domain.register(NormalSubscriber, stream="normal_stream")
    test_domain.register(ErrorSubscriber, stream="error_stream")
    test_domain.register(
        ErrorInErrorHandlerSubscriber, stream="error_in_error_handler_stream"
    )

    test_domain.init(traverse=False)


@pytest.mark.asyncio
async def test_event_handler_error_handling(test_domain, caplog):
    """Test that handle_error is called when an exception occurs in an event handler"""
    # Create test event
    user_id = str(uuid4())
    user = User(
        id=user_id, email="john.doe@example.com", name="John Doe", password_hash="hash"
    )
    user.raise_(
        Registered(
            id=user_id,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )
    message = Message.from_domain_object(user._events[-1])

    # Create engine
    engine = Engine(domain=test_domain, test_mode=True)

    # Test normal handler
    await engine.handle_message(NormalEventHandler, message)
    assert handler_counter == 1
    assert error_handler_counter == 0

    # Test handler with error that has handle_error
    await engine.handle_message(ErrorEventHandler, message)
    assert handler_counter == 2  # +1 from the handler
    assert error_handler_counter == 1  # +1 from handle_error

    # Test handler with error in handle_error
    await engine.handle_message(ErrorInErrorHandlerEventHandler, message)
    assert handler_counter == 3  # +1 from the handler
    assert error_in_error_handler_counter == 1  # +1 from handle_error

    # Verify engine is still running
    assert not engine.shutting_down

    # Verify errors were logged appropriately
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) >= 3  # At least 1 for each error case

    # Check for specific error messages
    assert any("Error in error handler" in record.message for record in error_logs)


@pytest.mark.asyncio
async def test_command_handler_error_handling(test_domain, caplog):
    """Test that handle_error is called when an exception occurs in a command handler"""
    # Create test command
    command = Register(
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    message = Message.from_domain_object(
        test_domain._enrich_command(command, asynchronous=True)
    )

    # Create engine
    engine = Engine(domain=test_domain, test_mode=True)

    # Test normal handler
    await engine.handle_message(NormalCommandHandler, message)
    assert handler_counter == 1
    assert error_handler_counter == 0

    # Test handler with error that has handle_error
    await engine.handle_message(ErrorCommandHandler, message)
    assert handler_counter == 2  # +1 from the handler
    assert error_handler_counter == 1  # +1 from handle_error

    # Test handler with error in handle_error
    await engine.handle_message(ErrorInErrorHandlerCommandHandler, message)
    assert handler_counter == 3  # +1 from the handler
    assert error_in_error_handler_counter == 1  # +1 from handle_error

    # Verify engine is still running
    assert not engine.shutting_down

    # Verify errors were logged appropriately
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) >= 3  # At least 1 for each error case

    # Check for specific error messages
    assert any("Error in error handler" in record.message for record in error_logs)


@pytest.mark.asyncio
async def test_subscriber_error_handling(test_domain, caplog):
    """Test that handle_error is called when an exception occurs in a subscriber"""
    # Create test message for broker
    test_message = {"data": "test_data"}

    # Create engine
    engine = Engine(domain=test_domain, test_mode=True)

    # Test normal subscriber
    await engine.handle_broker_message(NormalSubscriber, test_message)
    assert broker_handler_counter == 1
    assert broker_error_handler_counter == 0

    # Test subscriber with error that has handle_error
    await engine.handle_broker_message(ErrorSubscriber, test_message)
    assert broker_handler_counter == 2  # +1 from the handler
    assert broker_error_handler_counter == 1  # +1 from handle_error

    # Test subscriber with error in handle_error
    await engine.handle_broker_message(ErrorInErrorHandlerSubscriber, test_message)
    assert broker_handler_counter == 3  # +1 from the handler
    assert (
        broker_error_handler_counter == 2
    )  # +1 from handle_error (this is now correct)

    # Verify engine is still running
    assert not engine.shutting_down

    # Verify errors were logged appropriately
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(error_logs) >= 3  # At least 1 for each error case

    # Check for specific error messages
    assert any("Error in error handler" in record.message for record in error_logs)
