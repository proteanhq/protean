"""End-to-end tests for StreamSubscription with real Redis broker."""

import asyncio
import pytest
from uuid import uuid4

from protean.utils.mixins import handle
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String, Integer
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.globals import current_domain


failed_count = 0


class User(BaseAggregate):
    email = String(identifier=True)
    name = String()
    password_hash = String()

    @classmethod
    def register(cls, email: str, name: str, password: str):
        user = cls(
            email=email,
            name=name,
            password_hash=f"hashed_{password}",
        )
        user.raise_(
            UserRegistered(
                email=user.email,
                name=user.name,
            )
        )
        return user


class UserRegistered(BaseEvent):
    email = String(required=True)
    name = String(required=True)


class SendWelcomeEmail(BaseCommand):
    email = String(required=True)
    name = String(required=True)


class Notification(BaseAggregate):
    notification_id = Identifier(identifier=True)
    user_email = String()
    message = String()
    sent_count = Integer(default=0)

    @classmethod
    def create(cls, user_email: str, message: str):
        return cls(
            notification_id=str(uuid4()),
            user_email=user_email,
            message=message,
        )

    def mark_sent(self):
        self.sent_count += 1


# Event and Command Handlers
class WelcomeEmailHandler(BaseEventHandler):
    """Handles UserRegistered event and sends welcome email command."""

    @handle(UserRegistered)
    def send_welcome(self, event: UserRegistered):
        # Simulate sending a command
        current_domain.process(
            SendWelcomeEmail(
                email=event.email,
                name=event.name,
            )
        )


class NotificationCommandHandler(BaseCommandHandler):
    """Handles notification commands."""

    @handle(SendWelcomeEmail)
    def handle_send_welcome(self, command: SendWelcomeEmail):
        # Create and save notification
        notification = Notification.create(
            user_email=command.email,
            message=f"Welcome {command.name}!",
        )
        notification.mark_sent()
        current_domain.repository_for(Notification).add(notification)


# Create a handler that always fails
class AlwaysFailingHandler(BaseEventHandler):
    @handle(UserRegistered)
    def process(self, event):
        raise Exception("Always fails")


class FailingHandler(BaseEventHandler):
    @handle(UserRegistered)
    def process(self, event):
        global failed_count
        if failed_count < 2:
            failed_count += 1
            raise Exception("Simulated failure")
        # Success on third attempt


@pytest.mark.redis
class TestEndToEndFlow:
    @pytest.fixture(autouse=True)
    def setup(self, test_domain):
        """Setup test domain with stream subscriptions."""
        # Register aggregates
        test_domain.register(User)
        test_domain.register(Notification)

        # Register events and commands
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(AlwaysFailingHandler, part_of=User)
        test_domain.register(FailingHandler, part_of=User)
        test_domain.register(SendWelcomeEmail, part_of=Notification)

        # Register handlers
        test_domain.register(WelcomeEmailHandler, part_of=User)
        test_domain.register(NotificationCommandHandler, part_of=Notification)

        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_event_to_command_flow(self, test_domain):
        """Test full flow from event to command processing via streams."""
        # Start the engine in test mode
        engine = Engine(test_domain, test_mode=True)

        # Verify handlers are registered
        assert fqn(WelcomeEmailHandler) in engine._subscriptions
        assert fqn(NotificationCommandHandler) in engine._subscriptions

        # Create and save a user aggregate (this will emit UserRegistered event)
        user = User.register(
            email="test@example.com",
            name="Test User",
            password="password123",
        )
        test_domain.repository_for(User).add(user)

        # Process outbox to publish to Redis stream
        # In a real scenario, the OutboxProcessor would handle this
        outbox_processor = engine._outbox_processors.get(
            "outbox-processor-default-to-default"
        )
        if outbox_processor:
            await outbox_processor.initialize()
            # Process a few ticks to ensure messages are published
            for _ in range(3):
                await outbox_processor.tick()

        # Start subscriptions briefly to process messages
        for subscription in engine._subscriptions.values():
            await subscription.initialize()
            # Process one batch
            messages = await subscription.get_next_batch_of_messages()
            if messages:
                await subscription.process_batch(messages)

        # Verify notification was created
        notifications = test_domain.repository_for(Notification)._dao.query.all().items
        assert len(notifications) > 0
        notification = notifications[0]
        assert notification.user_email == "test@example.com"
        assert "Welcome Test User" in notification.message
        assert notification.sent_count == 1

    @pytest.mark.asyncio
    async def test_multiple_consumers_same_group(self, test_domain):
        """Test that multiple consumers in same group share work."""
        # Start two engines (simulating two server instances)
        engine1 = Engine(test_domain, test_mode=True)
        engine2 = Engine(test_domain, test_mode=True)

        # Both engines should have the same handlers
        handler_name = fqn(WelcomeEmailHandler)
        subscription1 = engine1._subscriptions[handler_name]
        subscription2 = engine2._subscriptions[handler_name]

        # Initialize both subscriptions
        await subscription1.initialize()
        await subscription2.initialize()

        # Verify they have same consumer group but different consumer names
        assert subscription1.consumer_group == subscription2.consumer_group
        assert subscription1.consumer_name != subscription2.consumer_name

        # Publish multiple messages directly to stream
        broker = test_domain.brokers["default"]
        messages = []
        for i in range(10):
            message = {
                "data": {
                    "email": f"user{i}@example.com",
                    "name": f"User {i}",
                },
                "metadata": {
                    "headers": {
                        "id": f"msg-{i}",
                        "type": "UserRegistered",
                        "stream": "email",
                        "time": "2024-01-01T00:00:00Z",
                    },
                    "envelope": {"specversion": "1.0"},
                },
            }
            msg_id = broker.publish("email", message)
            messages.append((msg_id, message))

        # Both consumers read messages
        batch1 = await subscription1.get_next_batch_of_messages()
        batch2 = await subscription2.get_next_batch_of_messages()

        # Verify messages were distributed (not duplicated)
        ids1 = {msg[0] for msg in batch1}
        ids2 = {msg[0] for msg in batch2}
        assert len(ids1.intersection(ids2)) == 0  # No overlap
        assert len(batch1) + len(batch2) <= 10  # Total not more than published

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, test_domain):
        """Test that failed messages are retried."""
        engine = Engine(test_domain, test_mode=True)

        handler = test_domain.registry.event_handlers[fqn(FailingHandler)].cls

        # Create subscription with short retry delay
        subscription = StreamSubscription(
            engine,
            "test",
            handler,
            max_retries=3,
            retry_delay_seconds=0.1,
        )

        await subscription.initialize()

        # Publish a test message
        broker = test_domain.brokers["default"]
        user = User.register(
            email="test@example.com",
            name="Test User",
            password="password123",
        )
        message = Message.from_domain_object(user._events[0])
        broker.publish("test", message.to_dict())

        # Process with retries
        for attempt in range(3):
            messages = await subscription.get_next_batch_of_messages()
            if messages:
                await subscription.process_batch(messages)
                await asyncio.sleep(0.2)  # Wait for retry delay

        # Verify message was eventually processed
        assert failed_count == 2  # Failed twice, succeeded on third

    @pytest.mark.asyncio
    async def test_dlq_for_permanently_failed_messages(self, test_domain):
        """Test that permanently failed messages go to DLQ."""
        engine = Engine(test_domain, test_mode=True)

        handler = test_domain.registry.event_handlers[fqn(AlwaysFailingHandler)].cls

        # Create subscription with DLQ enabled
        subscription = StreamSubscription(
            engine,
            "failing",
            handler,
            max_retries=2,
            retry_delay_seconds=0.01,
            enable_dlq=True,
        )

        await subscription.initialize()

        # Publish a message
        broker = test_domain.brokers["default"]
        message = {
            "data": {"email": "fail@example.com", "name": "Fail"},
            "metadata": {
                "headers": {
                    "id": "msg-dlq-test",
                    "type": "UserRegistered",
                    "stream": "failing",
                    "time": "2024-01-01T00:00:00Z",
                },
                "envelope": {"specversion": "1.0"},
            },
        }
        broker.publish("failing", message)

        # Process message (will fail and retry)
        for _ in range(3):
            messages = await subscription.get_next_batch_of_messages()
            if messages:
                await subscription.process_batch(messages)
                await asyncio.sleep(0.05)

        # Check DLQ stream
        dlq_messages = broker._read("failing:dlq", "dlq-reader", 10)
        assert len(dlq_messages) > 0

        # Verify DLQ message has metadata
        dlq_msg = dlq_messages[0][1]
        assert "_dlq_metadata" in dlq_msg
        assert dlq_msg["_dlq_metadata"]["original_stream"] == "failing"
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 2

    @pytest.mark.asyncio
    async def test_stream_subscription_in_engine(self, test_domain):
        """Test that Engine correctly uses StreamSubscription based on config."""
        # Verify configuration
        assert test_domain.config["server"]["subscription_type"] == "stream"

        # Create engine
        engine = Engine(test_domain, test_mode=True)

        # Check that StreamSubscription was used (not EventStoreSubscription)
        for subscription in engine._subscriptions.values():
            assert isinstance(subscription, StreamSubscription)

        # Verify subscription configuration matches domain config
        server_config = test_domain.config["server"]
        stream_config = server_config["stream_subscription"]
        for subscription in engine._subscriptions.values():
            assert subscription.messages_per_tick == server_config["messages_per_tick"]
            assert (
                subscription.blocking_timeout_ms == stream_config["blocking_timeout_ms"]
            )
            assert subscription.max_retries == stream_config["max_retries"]
            assert (
                subscription.retry_delay_seconds == stream_config["retry_delay_seconds"]
            )
            assert subscription.enable_dlq == stream_config["enable_dlq"]
