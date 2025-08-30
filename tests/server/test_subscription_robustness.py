import logging
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.broker_subscription import BrokerSubscription
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.utils.eventing import Metadata
from protean.utils.eventing import Message
from protean.utils.mixins import handle

# Set up logger
logger = logging.getLogger(__name__)

# Counter variables to track method calls
event_handler_counter = 0
error_handler_counter = 0
broker_counter = 0


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


class SyncRegistered(BaseEvent):
    """Registered event that will be processed synchronously"""

    id = Identifier()
    email = String()
    name = String()


class EmailSent(BaseEvent):
    id = Identifier()
    email = String()


# Event handlers
class CountingEventHandler(BaseEventHandler):
    """An event handler that counts invocations"""

    @handle(Registered)
    def handle_registered(self, event):
        global event_handler_counter
        event_handler_counter += 1

    @handle(EmailSent)
    def handle_email_sent(self, event):
        global event_handler_counter
        event_handler_counter += 1


class FailingEventHandler(BaseEventHandler):
    """An event handler that raises exceptions for Registered events"""

    @handle(Registered)
    def handle_registered(self, event):
        global event_handler_counter
        event_handler_counter += 1
        # Raise an exception (will be caught by Engine.handle_message)
        raise Exception("Intentional exception for testing")

    @handle(EmailSent)
    def handle_email_sent(self, event):
        global event_handler_counter
        event_handler_counter += 1

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


class UnhandledExceptionEventHandler(BaseEventHandler):
    """
    An event handler that raises an exception that should not be counted as successful
    """

    @handle(Registered)
    def handle_registered(self, event):
        # This exception will be caught by Engine.handle_message
        global event_handler_counter
        event_handler_counter += 1
        raise RuntimeError("Unhandled exception in event handler")

    @classmethod
    def handle_error(cls, exc, message):
        # Handle the error (but it will still return False from handle_message)
        pass


# Broker subscribers
class CountingSubscriber(BaseSubscriber):
    """A subscriber that counts invocations"""

    def __call__(self, data: dict):
        global broker_counter
        broker_counter += 1


class FailingSubscriber(BaseSubscriber):
    """A subscriber that always raises an exception"""

    def __call__(self, data: dict):
        global broker_counter
        broker_counter += 1
        # Raise an exception (will be caught by Engine.handle_broker_message)
        raise Exception("Intentional exception for testing")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


@pytest.fixture(autouse=True)
def reset_counters():
    """Reset the counters before each test"""
    global event_handler_counter, error_handler_counter, broker_counter
    event_handler_counter = 0
    error_handler_counter = 0
    broker_counter = 0


@pytest.fixture(autouse=True)
def register(test_domain):
    """Setup a domain with our robustness test classes"""
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(SyncRegistered, part_of=User)
    test_domain.register(EmailSent, part_of=User)

    test_domain.register(CountingEventHandler, part_of=User)
    test_domain.register(FailingEventHandler, part_of=User)
    test_domain.register(UnhandledExceptionEventHandler, part_of=User)

    test_domain.register(CountingSubscriber, stream="success_stream")
    test_domain.register(FailingSubscriber, stream="failure_stream")

    test_domain.init(traverse=False)


def create_event_message(event_cls, user_id, asynchronous=True, **kwargs):
    """Helper function to create an event message"""
    event = event_cls(id=user_id, **kwargs)
    message = Message.to_message(event)

    # Set asynchronous explicitly
    if not asynchronous:
        message.metadata = Metadata(message.metadata.to_dict(), asynchronous=False)

    return message


@pytest.mark.asyncio
async def test_subscription_process_batch_with_asynchronous_flag(test_domain, caplog):
    """Test that Subscription.process_batch correctly checks the asynchronous flag"""
    # Setup engine
    engine = Engine(domain=test_domain, test_mode=False)

    # Create a subscription with a real handler
    subscription = EventStoreSubscription(
        engine,
        "test",  # User stream category
        CountingEventHandler,
        messages_per_tick=10,
        position_update_interval=1,
    )

    # Create test messages with different asynchronous flags
    messages = []

    # Create a synchronous message (should be skipped by the subscription)
    user_id = str(uuid4())
    sync_message = create_event_message(
        SyncRegistered,
        user_id,
        asynchronous=False,
        email="sync@example.com",
        name="Sync User",
    )
    messages.append(sync_message)

    # Create an asynchronous message (should be processed)
    async_message = create_event_message(
        Registered,
        user_id,
        asynchronous=True,
        email="async@example.com",
        name="Async User",
        password_hash="hash",
    )
    messages.append(async_message)

    # Set up logging to capture debug messages
    with caplog.at_level(logging.DEBUG):
        # Process the batch
        result = await subscription.process_batch(messages)

        # Check counting
        global event_handler_counter
        # Only the async message should be processed
        assert event_handler_counter == 1
        assert result == 1  # One successful message

        # Verify the message was processed and logged
        assert (
            f"{async_message.metadata.headers.type}-{async_message.metadata.headers.id}"
            in caplog.text
        )

        # Check if position updates were written
        position_messages = test_domain.event_store.store.read(
            "position-tests.server.test_subscription_robustness.CountingEventHandler-test"
        )
        assert len(position_messages) > 0


@pytest.mark.asyncio
async def test_subscription_process_batch_exception_handling(test_domain, caplog):
    """Test that Subscription.process_batch handles exceptions from event handler and doesn't count them as successful"""
    # Setup engine
    engine = Engine(domain=test_domain, test_mode=False)

    # Create a subscription with the handler that raises exceptions
    subscription = EventStoreSubscription(
        engine,
        "test",  # User stream category
        UnhandledExceptionEventHandler,
        messages_per_tick=10,
        position_update_interval=1,
    )

    # Create a test message that will cause the handler to fail
    user_id = str(uuid4())
    failing_message = create_event_message(
        Registered,
        user_id,
        email="test@example.com",
        name="Test User",
        password_hash="hash",
    )

    # Reset event handler counter
    global event_handler_counter
    event_handler_counter = 0

    # Set up logging to capture the error from process_batch
    with caplog.at_level(logging.ERROR):
        # Process the batch
        result = await subscription.process_batch([failing_message])

        # Verify handler was called but not counted as successful
        assert event_handler_counter == 1  # The handler was executed
        assert result == 0  # But no messages were processed successfully

        # Verify error was reported and logged
        assert "Error handling message" in caplog.text
        assert "Unhandled exception in event handler" in caplog.text

        # Check if position was still updated in the event store despite the error
        position_messages = test_domain.event_store.store.read(
            "position-tests.server.test_subscription_robustness.UnhandledExceptionEventHandler-test"
        )
        assert len(position_messages) > 0


@pytest.mark.asyncio
async def test_broker_subscription_process_batch_exception_handling(
    test_domain, caplog
):
    """Test that BrokerSubscription.process_batch properly handles exceptions"""
    # Setup engine
    engine = Engine(domain=test_domain, test_mode=False)

    # Get broker
    broker = test_domain.brokers["default"]

    # Create a broker subscription with the failing subscriber
    subscription = BrokerSubscription(
        engine,
        broker,
        "failure_stream",  # This stream has our failing subscriber
        FailingSubscriber,
        messages_per_tick=10,
    )

    # Create test broker messages - don't publish to the broker
    messages = [
        (str(uuid4()), {"message": "Test message 1"}),
        (str(uuid4()), {"message": "Test message 2"}),
    ]

    # Set up logging to capture errors
    with caplog.at_level(logging.ERROR):
        # Process the batch directly
        result = await subscription.process_batch(messages)

        # Verify no messages were processed successfully
        assert result == 0

        # Verify error handler was called
        global error_handler_counter
        assert error_handler_counter >= 2  # Once for each message

        # Verify error was logged
        assert "Error handling message in FailingSubscriber" in caplog.text
        assert "Intentional exception for testing" in caplog.text


@pytest.mark.asyncio
async def test_subscription_with_mixed_success_and_failure(test_domain, caplog):
    """Test that Subscription.process_batch handles a mix of successful and failing messages"""
    # Reset counters
    global event_handler_counter, error_handler_counter
    event_handler_counter = 0
    error_handler_counter = 0

    # Setup engine
    engine = Engine(domain=test_domain, test_mode=False)

    # Create a subscription with the failing handler
    subscription = EventStoreSubscription(
        engine,
        "test",  # User stream category
        FailingEventHandler,  # This handler fails for Registered but succeeds for EmailSent
        messages_per_tick=10,
        position_update_interval=1,
    )

    # Create a mix of messages - some will fail, some will succeed
    messages = []
    user_id = str(uuid4())

    # This will fail (Registered events trigger exceptions)
    failing_message = create_event_message(
        Registered,
        user_id,
        email="fail@example.com",
        name="Failing User",
        password_hash="hash",
    )
    messages.append(failing_message)

    # This will succeed (EmailSent events don't trigger exceptions)
    succeeding_message = create_event_message(
        EmailSent, user_id, email="success@example.com"
    )
    messages.append(succeeding_message)

    # Process the batch
    with caplog.at_level(logging.ERROR):
        result = await subscription.process_batch(messages)

        # Verify one message was processed successfully
        assert result == 1

        # Verify error was logged for the failing message
        assert "Error handling message" in caplog.text
        assert "Intentional exception for testing" in caplog.text

        # Verify handler counter reflects the succeeded message
        assert (
            event_handler_counter >= 1
        )  # At least the EmailSent event was processed successfully
        assert (
            error_handler_counter >= 1
        )  # Error handler called for the Registered event

        # Check if position was updated for both messages
        position_messages = test_domain.event_store.store.read(
            "position-tests.server.test_subscription_robustness.FailingEventHandler-test"
        )
        assert len(position_messages) > 0  # At least one position update
