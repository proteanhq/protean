from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.utils import Processing
from protean.utils.eventing import Metadata, DomainMeta, Message
from protean.utils.mixins import handle

# Global variables to track processing
event_counter = 0
command_counter = 0
broker_message_counter = 0
error_counter = 0
error_handler_error_counter = 0


# Reset counters between tests
@pytest.fixture(autouse=True)
def reset_counters():
    global \
        event_counter, \
        command_counter, \
        broker_message_counter, \
        error_counter, \
        error_handler_error_counter
    event_counter = 0
    command_counter = 0
    broker_message_counter = 0
    error_counter = 0
    error_handler_error_counter = 0


# Event-based test classes
class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class EmailSent(BaseEvent):
    id = Identifier()
    email = String()


# Event handlers
class SuccessfulEventHandler(BaseEventHandler):
    @handle(EmailSent)
    def record_email_sent(self, event: EmailSent) -> None:
        global event_counter
        event_counter += 1


class FailingEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        global error_counter
        error_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        # This handler successfully processes errors
        global error_counter
        error_counter += 1


class FailingErrorHandlerEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        global error_handler_error_counter
        error_handler_error_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_error_counter
        error_handler_error_counter += 1
        # This error handler itself raises an exception
        raise Exception("Error in error handler")


# Command-based test classes
class RegisterUser(BaseCommand):
    email = String()
    name = String()
    password_hash = String()


class SendEmail(BaseCommand):
    email = String()


class SuccessfulCommandHandler(BaseCommandHandler):
    @handle(SendEmail)
    def send_email(self, command: SendEmail) -> None:
        global command_counter
        command_counter += 1


class FailingCommandHandler(BaseCommandHandler):
    @handle(RegisterUser)
    def register_user(self, command: RegisterUser) -> None:
        global error_counter
        error_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_counter
        error_counter += 1


class FailingErrorHandlerCommandHandler(BaseCommandHandler):
    @handle(RegisterUser)
    def register_user(self, command: RegisterUser) -> None:
        global error_handler_error_counter
        error_handler_error_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_error_counter
        error_handler_error_counter += 1
        # This error handler itself raises an exception
        raise Exception("Error in error handler")


# Broker message subscribers
class SuccessfulSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        global broker_message_counter
        broker_message_counter += 1


class FailingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        global error_counter
        error_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_counter
        error_counter += 1


class FailingErrorHandlerSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        global error_handler_error_counter
        error_handler_error_counter += 1
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_error_counter
        error_handler_error_counter += 1
        # This error handler itself raises an exception
        raise Exception("Error in error handler")


@pytest.fixture
def robust_test_domain(test_domain):
    # Configure domain for async processing
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.config["message_processing"] = Processing.ASYNC.value
    test_domain.config["command_processing"] = Processing.ASYNC.value

    # Register event-related classes
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(EmailSent, part_of=User)
    test_domain.register(SuccessfulEventHandler, part_of=User)
    test_domain.register(FailingEventHandler, part_of=User)
    test_domain.register(FailingErrorHandlerEventHandler, part_of=User)

    # Register command-related classes
    test_domain.register(RegisterUser, part_of=User)
    test_domain.register(SendEmail, part_of=User)
    test_domain.register(SuccessfulCommandHandler, part_of=User)
    test_domain.register(FailingCommandHandler, part_of=User)
    test_domain.register(FailingErrorHandlerCommandHandler, part_of=User)

    # Register broker subscribers
    test_domain.register(SuccessfulSubscriber, stream="success_stream")
    test_domain.register(FailingSubscriber, stream="failure_stream")
    test_domain.register(
        FailingErrorHandlerSubscriber, stream="failing_error_handler_stream"
    )

    test_domain.init(traverse=False)
    return test_domain


def test_events_continue_processing_after_exceptions(robust_test_domain):
    """Test that event processing continues even after exceptions"""
    # Create a user and raise events
    user_id = str(uuid4())
    user = User(
        id=user_id,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )

    # Raise event that will fail
    user.raise_(
        Registered(
            id=user_id,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    # Raise event that will succeed
    user.raise_(
        EmailSent(
            id=user_id,
            email="john.doe@example.com",
        )
    )

    # Add to repository
    robust_test_domain.repository_for(User).add(user)

    # Create engine with test_mode=True to ensure it processes all messages and then shuts down
    engine = Engine(domain=robust_test_domain, test_mode=True)

    # Run the engine (in test_mode it will automatically shut down after processing all messages)
    engine.run()

    # In test_mode, engine.shutting_down will be True after run() completes
    # So we don't check that flag but instead verify processing was successful

    # Verify events were processed
    global event_counter, error_counter
    assert event_counter == 1  # Successfully processed the EmailSent event
    assert error_counter == 2  # Counted the error and processed by error handler

    # Verify position was updated by checking messages in the event store
    messages = robust_test_domain.event_store.store.read("$all")
    # We should have at least 3 messages:
    # 1. The Registered event
    # 2. The EmailSent event
    # 3. At least one read position update message
    assert len(messages) >= 3


def test_failing_error_handlers_dont_crash_engine(robust_test_domain):
    """Test that the engine continues running even when error handlers fail"""
    # Create a user and raise an event
    user_id = str(uuid4())
    user = User(
        id=user_id,
        email="jane.doe@example.com",
        name="Jane Doe",
        password_hash="hash",
    )

    # Raise event that will trigger a failing error handler
    user.raise_(
        Registered(
            id=user_id,
            email="jane.doe@example.com",
            name="Jane Doe",
            password_hash="hash",
        )
    )

    # Add to repository
    robust_test_domain.repository_for(User).add(user)

    # Run the engine
    engine = Engine(domain=robust_test_domain, test_mode=True)
    engine.run()

    # In test_mode, engine will automatically shut down after processing
    # So we verify by checking that error handlers were called

    # Verify error handler was called and counted
    global error_handler_error_counter
    assert (
        error_handler_error_counter == 2
    )  # Both handler and error handler were called


def test_commands_continue_processing_after_exceptions(robust_test_domain):
    """Test that command processing continues even after exceptions"""
    # Create and process failing command
    failing_command = RegisterUser(
        email="john.doe@example.com", name="John Doe", password_hash="hash"
    )
    robust_test_domain.process(failing_command, asynchronous=True)

    # Create and process successful command
    successful_command = SendEmail(email="john.doe@example.com")
    robust_test_domain.process(successful_command, asynchronous=True)

    # Run the engine
    engine = Engine(domain=robust_test_domain, test_mode=True)
    engine.run()

    # In test_mode, engine will automatically shut down after processing
    # So we verify by checking that commands were processed

    # Verify commands were processed
    global command_counter, error_counter
    assert command_counter == 1  # Successfully processed the SendEmail command
    assert error_counter >= 2  # Processed both the error and error handler


def test_broker_messages_continue_processing_after_exceptions(robust_test_domain):
    """Test that broker message processing continues even after exceptions"""
    # Publish messages to broker
    robust_test_domain.brokers["default"].publish(
        "failure_stream", {"message": "This will fail"}
    )
    robust_test_domain.brokers["default"].publish(
        "success_stream", {"message": "This will succeed"}
    )
    robust_test_domain.brokers["default"].publish(
        "failing_error_handler_stream",
        {"message": "This will fail with error in error handler"},
    )

    # Run the engine
    engine = Engine(domain=robust_test_domain, test_mode=True)
    engine.run()

    # In test_mode, engine will automatically shut down after processing
    # So we verify by checking that messages were processed

    # Verify broker messages were processed
    global broker_message_counter, error_counter, error_handler_error_counter
    assert (
        broker_message_counter == 1
    )  # Successfully processed the success stream message
    assert error_counter >= 2  # Processed both the error and error handler
    assert (
        error_handler_error_counter >= 2
    )  # Both handler and error handler were called


@pytest.mark.asyncio
async def test_event_handler_continues_after_exception(robust_test_domain):
    """Test individual event handler message processing resilience"""
    engine = Engine(domain=robust_test_domain, test_mode=True)

    # Create events
    user_id = str(uuid4())
    failing_event = Registered(
        id=user_id, email="john.doe@example.com", name="John Doe", password_hash="hash"
    )

    successful_event = EmailSent(id=user_id, email="john.doe@example.com")

    # Create messages from events
    failing_message = Message.to_message(failing_event)
    successful_message = Message.to_message(successful_event)

    # Process failing message first
    await engine.handle_message(FailingEventHandler, failing_message)

    # Process successful message next - this should still work even after the error
    await engine.handle_message(SuccessfulEventHandler, successful_message)

    # Verify both messages were processed - this confirms error handling worked
    global event_counter, error_counter
    assert event_counter == 1  # Successfully processed EmailSent event
    assert error_counter == 2  # Counted both error and error handler


@pytest.mark.asyncio
async def test_broker_message_handling_continues_after_exception(robust_test_domain):
    """Test individual broker message handling resilience"""
    engine = Engine(domain=robust_test_domain, test_mode=True)

    # Create broker messages
    failing_message = {"message": "This will fail"}
    successful_message = {"message": "This will succeed"}

    # Process failing message first
    await engine.handle_broker_message(FailingSubscriber, failing_message)

    # Process successful message next - this should still work even after the error
    await engine.handle_broker_message(SuccessfulSubscriber, successful_message)

    # Verify both messages were processed - this confirms error handling worked
    global broker_message_counter, error_counter
    assert broker_message_counter == 1  # Successfully processed message
    assert error_counter == 2  # Counted both error and error handler


def test_mixed_error_scenarios(robust_test_domain):
    """Test a mix of events, commands, and broker messages with various error scenarios"""
    # Create user and events
    user_id = str(uuid4())
    user = User(
        id=user_id,
        email="mixed@example.com",
        name="Mixed User",
        password_hash="hash",
    )

    # Add failing and successful events
    user.raise_(
        Registered(  # Will trigger FailingEventHandler
            id=user_id,
            email="mixed@example.com",
            name="Mixed User",
            password_hash="hash",
        )
    )
    user.raise_(
        EmailSent(  # Will trigger SuccessfulEventHandler
            id=user_id,
            email="mixed@example.com",
        )
    )

    # Add to repository
    robust_test_domain.repository_for(User).add(user)

    # Process failing and successful commands
    failing_command = RegisterUser(  # Will trigger FailingCommandHandler
        email="mixed@example.com", name="Mixed User", password_hash="hash"
    )
    robust_test_domain.process(failing_command, asynchronous=True)

    successful_command = SendEmail(  # Will trigger SuccessfulCommandHandler
        email="mixed@example.com"
    )
    robust_test_domain.process(successful_command, asynchronous=True)

    # Add broker messages
    robust_test_domain.brokers["default"].publish(
        "failure_stream", {"message": "This will fail"}
    )
    robust_test_domain.brokers["default"].publish(
        "success_stream", {"message": "This will succeed"}
    )
    robust_test_domain.brokers["default"].publish(
        "failing_error_handler_stream",
        {"message": "This will fail with error handler failure"},
    )

    # Run the engine
    engine = Engine(domain=robust_test_domain, test_mode=True)
    engine.run()

    # In test_mode, engine will automatically shut down after processing
    # So we verify by checking all types of messages were processed

    # Verify all types of messages were processed
    global \
        event_counter, \
        command_counter, \
        broker_message_counter, \
        error_counter, \
        error_handler_error_counter
    assert event_counter >= 1  # At least one successful event
    assert command_counter >= 1  # At least one successful command
    assert broker_message_counter >= 1  # At least one successful broker message
    assert error_counter >= 2  # At least one error with successful error handling
    assert (
        error_handler_error_counter >= 2
    )  # At least one error with failing error handling


@pytest.mark.asyncio
async def test_subscription_with_messages_of_varying_flags(robust_test_domain):
    """Test that subscription properly handles messages with varying asynchronous flags"""
    engine = Engine(domain=robust_test_domain, test_mode=True)

    # Create a subscription manually
    subscription = EventStoreSubscription(
        engine,
        "test_category",
        SuccessfulEventHandler,
        messages_per_tick=10,
    )

    # Create test messages with different asynchronous flags
    messages = []

    # Create a synchronous message (should be skipped)
    sync_event = EmailSent(id=str(uuid4()), email="sync@example.com")
    sync_message = Message.to_message(sync_event)

    # Force-construct a synchronous message
    domain_meta = DomainMeta(sync_message.metadata.domain.to_dict(), asynchronous=False)
    sync_message.metadata = Metadata(
        sync_message.metadata.to_dict(), domain=domain_meta.to_dict()
    )
    messages.append(sync_message)

    # Create an asynchronous message (should be processed)
    async_event = EmailSent(id=str(uuid4()), email="async@example.com")
    async_message = Message.to_message(async_event)  # Metadata is async by default
    messages.append(async_message)

    # Process the batch directly
    await subscription.process_batch(messages)

    # Verify only the async message was processed
    global event_counter
    assert event_counter == 1  # Only the async message should have been processed


@pytest.mark.asyncio
async def test_subscription_exception_handling_with_position_updates(
    robust_test_domain,
):
    """Test subscription ensures position updates even with exceptions"""
    engine = Engine(domain=robust_test_domain, test_mode=True)

    # Create a subscription
    subscription = EventStoreSubscription(
        engine,
        "test_category",
        FailingEventHandler,
        messages_per_tick=10,
    )

    # Create a test message
    event = Registered(
        id=str(uuid4()),
        email="test@example.com",
        name="Test User",
        password_hash="hash",
    )
    message = Message.to_message(event)

    # Mock only update_read_position to track calls
    original_update_read_position = subscription.update_read_position

    # Create a tracking mock
    position_updates = []

    async def mock_update_read_position(position):
        position_updates.append(position)
        return await original_update_read_position(position)

    # Apply the mock
    subscription.update_read_position = mock_update_read_position

    # Set message's global position for tracking
    message.global_position = 42

    # Update the asynchronous flag in the domain metadata
    old_domain_meta = message.metadata.domain
    new_domain_meta = DomainMeta(old_domain_meta.to_dict(), asynchronous=True)
    message.metadata = Metadata(message.metadata.to_dict(), domain=new_domain_meta)

    # Process the batch
    await subscription.process_batch([message])

    # Verify position was updated despite the error
    assert 42 in position_updates

    # Verify error was processed
    global error_counter
    assert error_counter >= 1


@pytest.mark.asyncio
async def test_error_handling_directly(robust_test_domain):
    """Test error handling directly at the engine level without using test_mode"""
    # Create Engine without test_mode
    engine = Engine(domain=robust_test_domain, test_mode=False)

    # Create a failing message
    user_id = str(uuid4())
    failing_event = Registered(
        id=user_id, email="direct@example.com", name="Direct Test", password_hash="hash"
    )
    failing_message = Message.to_message(failing_event)

    # Manually process message - this should not shut down the engine
    await engine.handle_message(FailingEventHandler, failing_message)

    # Verify the engine is NOT shutting down
    assert not engine.shutting_down
    assert engine.exit_code == 0

    # Verify error handling worked
    global error_counter
    assert error_counter >= 1  # Error was counted/handled


@pytest.mark.asyncio
async def test_failing_error_handler_directly(robust_test_domain):
    """Test that failing error handlers don't crash the engine"""
    # Create Engine without test_mode
    engine = Engine(domain=robust_test_domain, test_mode=False)

    # Create a failing message
    user_id = str(uuid4())
    failing_event = Registered(
        id=user_id, email="direct@example.com", name="Direct Test", password_hash="hash"
    )
    failing_message = Message.to_message(failing_event)

    # Manually process message with a handler that has a failing error handler
    await engine.handle_message(FailingErrorHandlerEventHandler, failing_message)

    # Verify the engine is NOT shutting down
    assert not engine.shutting_down
    assert engine.exit_code == 0

    # Verify error handling worked
    global error_handler_error_counter
    assert error_handler_error_counter >= 1  # Error handler was called


@pytest.mark.asyncio
async def test_broker_error_handling_directly(robust_test_domain):
    """Test broker error handling directly at the engine level without using test_mode"""
    # Create Engine without test_mode
    engine = Engine(domain=robust_test_domain, test_mode=False)

    # Create a failing broker message
    failing_message = {"message": "This will fail directly"}

    # Manually process message - this should not shut down the engine
    await engine.handle_broker_message(FailingSubscriber, failing_message)

    # Verify the engine is NOT shutting down
    assert not engine.shutting_down
    assert engine.exit_code == 0

    # Verify error handling worked
    global error_counter
    assert error_counter >= 1  # Error was counted/handled
