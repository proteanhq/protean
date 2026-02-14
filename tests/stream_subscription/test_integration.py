"""Integration tests for StreamSubscription with real broker and engine.

This module tests complete end-to-end workflows including:
- Real Redis broker integration
- Engine lifecycle management
- Event publishing and consumption
- Multi-handler scenarios
- Concurrent processing
"""

import asyncio
from uuid import uuid4

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Boolean, Identifier, Integer, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message


# Test Domain Models
class Account(BaseAggregate):
    """Account aggregate for integration tests."""

    account_id = Identifier(identifier=True)
    email = String()
    balance = Integer(default=0)
    is_active = Boolean(default=True)

    @classmethod
    def create_account(cls, email):
        account = cls(account_id=str(uuid4()), email=email)
        account.raise_(
            AccountCreated(account_id=account.account_id, email=account.email)
        )
        return account

    def deposit(self, amount):
        if not self.is_active:
            raise ValueError("Account is not active")

        old_balance = self.balance
        self.balance += amount

        self.raise_(
            MoneyDeposited(
                account_id=self.account_id,
                amount=amount,
                new_balance=self.balance,
                old_balance=old_balance,
            )
        )

    def deactivate(self):
        if self.is_active:
            self.is_active = False
            self.raise_(AccountDeactivated(account_id=self.account_id))


class AccountCreated(BaseEvent):
    """Event raised when an account is created."""

    account_id = Identifier(required=True)
    email = String()


class MoneyDeposited(BaseEvent):
    """Event raised when money is deposited."""

    account_id = Identifier(required=True)
    amount = Integer()
    new_balance = Integer()
    old_balance = Integer()


class AccountDeactivated(BaseEvent):
    """Event raised when an account is deactivated."""

    account_id = Identifier(required=True)


class SendWelcomeEmail(BaseCommand):
    """Command to send welcome email."""

    account_id = Identifier(required=True)
    email = String()


class UpdateAccountStatus(BaseCommand):
    """Command to update account status."""

    account_id = Identifier(required=True)
    is_active = Boolean()


# Test Handlers
class AccountNotificationHandler(BaseEventHandler):
    """Handler for account notification events."""

    notifications_sent = []
    should_fail = False

    @handle(AccountCreated)
    def send_welcome_notification(self, event):
        if self.should_fail:
            raise Exception("Notification service unavailable")

        self.notifications_sent.append(
            {"type": "welcome", "account_id": event.account_id, "email": event.email}
        )

    @handle(MoneyDeposited)
    def send_deposit_notification(self, event):
        if self.should_fail:
            raise Exception("Notification service unavailable")

        self.notifications_sent.append(
            {
                "type": "deposit",
                "account_id": event.account_id,
                "amount": event.amount,
                "new_balance": event.new_balance,
            }
        )


class AccountAuditHandler(BaseEventHandler):
    """Handler for account audit logging."""

    audit_logs = []

    @handle(AccountCreated)
    def log_account_creation(self, event):
        self.audit_logs.append(
            {
                "action": "account_created",
                "account_id": event.account_id,
                "email": event.email,
            }
        )

    @handle(MoneyDeposited)
    def log_deposit(self, event):
        self.audit_logs.append(
            {
                "action": "money_deposited",
                "account_id": event.account_id,
                "amount": event.amount,
            }
        )

    @handle(AccountDeactivated)
    def log_deactivation(self, event):
        self.audit_logs.append(
            {"action": "account_deactivated", "account_id": event.account_id}
        )


class EmailCommandHandler(BaseCommandHandler):
    """Handler for email commands."""

    emails_sent = []
    should_fail = False

    @handle(SendWelcomeEmail)
    def send_welcome_email(self, command):
        if self.should_fail:
            raise Exception("Email service unavailable")

        self.emails_sent.append(
            {
                "type": "welcome",
                "account_id": command.account_id,
                "email": command.email,
            }
        )


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    """Register domain elements for integration tests."""
    # Register domain elements
    test_domain.register(Account)
    test_domain.register(AccountCreated, part_of=Account)
    test_domain.register(MoneyDeposited, part_of=Account)
    test_domain.register(AccountDeactivated, part_of=Account)
    test_domain.register(SendWelcomeEmail, part_of=Account)
    test_domain.register(UpdateAccountStatus, part_of=Account)
    test_domain.register(AccountNotificationHandler, part_of=Account)
    test_domain.register(AccountAuditHandler, part_of=Account)
    test_domain.register(EmailCommandHandler, part_of=Account)
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    """Create test engine."""
    with test_domain.domain_context():
        return Engine(test_domain, test_mode=True)


@pytest.fixture(autouse=True)
def reset_handler_state():
    """Reset handler state before each test."""
    # Reset all handler class variables
    AccountNotificationHandler.notifications_sent = []
    AccountNotificationHandler.should_fail = False
    AccountAuditHandler.audit_logs = []
    EmailCommandHandler.emails_sent = []
    EmailCommandHandler.should_fail = False
    yield
    # Clean up after test
    AccountNotificationHandler.notifications_sent = []
    AccountNotificationHandler.should_fail = False
    AccountAuditHandler.audit_logs = []
    EmailCommandHandler.emails_sent = []
    EmailCommandHandler.should_fail = False


# Test Single Handler Integration
@pytest.mark.redis
async def test_complete_event_processing_workflow(test_domain, engine):
    """Test complete workflow from aggregate to handler."""
    with test_domain.domain_context():
        # Use unique stream name to avoid conflicts
        stream_name = f"account_notifications_{uuid4().hex[:8]}"

        # Set up engine and subscription
        subscription = StreamSubscription(
            engine=engine,
            stream_category=stream_name,
            handler=AccountNotificationHandler,
            blocking_timeout_ms=100,
        )

        # Create account and capture events before they're cleared
        account = Account.create_account("test@example.com")

        # Capture events before adding to repository (which clears them)
        events_to_publish = list(account._events)
        assert len(events_to_publish) > 0, "No events generated"

        # Now save the account (this clears _events)
        test_domain.repository_for(Account).add(account)

        # Manually publish the captured events (simulating outbox processor)
        for event in events_to_publish:
            message = Message.from_domain_object(event)
            msg_id = test_domain.brokers.get("default").publish(
                stream_name, message.to_dict()
            )
            assert msg_id, "Failed to publish message"

        # Initialize subscription AFTER publishing messages
        await subscription.initialize()

        # Process messages
        messages = await subscription.get_next_batch_of_messages()
        assert messages, "No messages retrieved from broker"

        result = await subscription.process_batch(messages)
        assert result > 0, f"No messages processed successfully. Result: {result}"

        # Verify handler processed the event
        assert len(AccountNotificationHandler.notifications_sent) == 1
        notification = AccountNotificationHandler.notifications_sent[0]
        assert notification["type"] == "welcome"
        assert notification["account_id"] == account.account_id
        assert notification["email"] == "test@example.com"


# Test Multi Handler Integration
@pytest.mark.redis
async def test_multiple_handlers_same_event(test_domain, engine):
    """Test that multiple handlers can process the same event."""
    with test_domain.domain_context():
        # Use unique stream names
        notif_stream = f"account_notifications_{uuid4().hex[:8]}"
        audit_stream = f"account_audit_{uuid4().hex[:8]}"

        # Set up engine and subscriptions
        notification_subscription = StreamSubscription(
            engine=engine,
            stream_category=notif_stream,
            handler=AccountNotificationHandler,
            blocking_timeout_ms=100,
        )

        audit_subscription = StreamSubscription(
            engine=engine,
            stream_category=audit_stream,
            handler=AccountAuditHandler,
            blocking_timeout_ms=100,
        )

        await notification_subscription.initialize()
        await audit_subscription.initialize()

        # Create account with events
        account = Account.create_account("multi@example.com")
        account.deposit(100)

        # Capture events before they're cleared
        events_to_publish = list(account._events)

        # Save account (clears events)
        test_domain.repository_for(Account).add(account)

        # Publish events to both streams
        broker = test_domain.brokers.get("default")
        for event in events_to_publish:
            message = Message.from_domain_object(event)
            broker.publish(notif_stream, message.to_dict())
            broker.publish(audit_stream, message.to_dict())

        # Process messages for both subscriptions
        notification_messages = (
            await notification_subscription.get_next_batch_of_messages()
        )
        audit_messages = await audit_subscription.get_next_batch_of_messages()

        if notification_messages:
            await notification_subscription.process_batch(notification_messages)

        if audit_messages:
            await audit_subscription.process_batch(audit_messages)

        # Verify both handlers processed events
        assert (
            len(AccountNotificationHandler.notifications_sent) == 2
        )  # welcome + deposit
        assert len(AccountAuditHandler.audit_logs) == 2  # creation + deposit

        # Verify correct event types
        notification_types = [
            n["type"] for n in AccountNotificationHandler.notifications_sent
        ]
        assert "welcome" in notification_types
        assert "deposit" in notification_types

        audit_actions = [a["action"] for a in AccountAuditHandler.audit_logs]
        assert "account_created" in audit_actions
        assert "money_deposited" in audit_actions


# Test Failure Recovery Integration
@pytest.mark.redis
async def test_handler_failure_with_retry_and_dlq(test_domain, engine):
    """Test complete failure, retry, and DLQ workflow."""
    with test_domain.domain_context():
        # Use unique stream name
        stream_name = f"account_notifications_{uuid4().hex[:8]}"

        # Set up failing handler
        AccountNotificationHandler.should_fail = True  # Make it fail

        subscription = StreamSubscription(
            engine=engine,
            stream_category=stream_name,
            handler=AccountNotificationHandler,
            max_retries=1,  # Reduce to 1 so it moves to DLQ faster
            retry_delay_seconds=0.001,
            enable_dlq=True,
            blocking_timeout_ms=100,
        )

        await subscription.initialize()

        # Track DLQ messages
        dlq_messages = []
        original_publish = subscription.broker.publish

        def track_dlq(stream, message):
            if stream.endswith(":dlq"):
                dlq_messages.append((stream, message))
            return original_publish(stream, message)

        subscription.broker.publish = track_dlq

        # Create and publish failing event
        account = Account.create_account("fail@example.com")

        # Capture events before clearing
        events_to_publish = list(account._events)
        test_domain.repository_for(Account).add(account)

        broker = test_domain.brokers.get("default")
        for event in events_to_publish:
            message = Message.from_domain_object(event)
            broker.publish(stream_name, message.to_dict())

        # Process messages - should fail and retry
        messages = await subscription.get_next_batch_of_messages()
        assert messages, "Should have messages to process"

        # Process batch will automatically handle the failures and move to DLQ after max_retries
        result = await subscription.process_batch(messages)
        assert result == 0  # No successful processing due to handler failure

        # The message should have been moved to DLQ after exhausting retries
        # (max_retries=2, so after 2 attempts it goes to DLQ)
        # The process_batch already handles the retry logic internally

        # Verify DLQ operation
        assert len(dlq_messages) >= 1, "Should have at least one message in DLQ"
        assert dlq_messages[0][0] == f"{stream_name}:dlq"
        assert "_dlq_metadata" in dlq_messages[0][1]


# Test Concurrent Processing
@pytest.mark.redis
async def test_concurrent_subscription_processing(test_domain, engine):
    """Test multiple subscriptions processing concurrently."""
    with test_domain.domain_context():
        # Create multiple subscriptions for different streams with unique names
        stream_names = [f"stream_{i}_{uuid4().hex[:8]}" for i in range(3)]
        subscriptions = []
        for stream_name in stream_names:
            subscription = StreamSubscription(
                engine=engine,
                stream_category=stream_name,
                handler=AccountNotificationHandler,
                blocking_timeout_ms=100,
            )
            await subscription.initialize()
            subscriptions.append(subscription)

        # Publish messages to each stream
        broker = test_domain.brokers.get("default")
        for i, stream_name in enumerate(stream_names):
            account = Account.create_account(f"test{i}@example.com")
            # Capture events before clearing
            events_to_publish = list(account._events)
            test_domain.repository_for(Account).add(account)

            for event in events_to_publish:
                message = Message.from_domain_object(event)
                broker.publish(stream_name, message.to_dict())

        # Process messages concurrently
        tasks = []
        for subscription in subscriptions:
            messages = await subscription.get_next_batch_of_messages()
            if messages:
                task = asyncio.create_task(subscription.process_batch(messages))
                tasks.append(task)

        # Wait for all processing to complete
        results = await asyncio.gather(*tasks)

        # Verify all subscriptions processed their messages
        assert all(result > 0 for result in results)
