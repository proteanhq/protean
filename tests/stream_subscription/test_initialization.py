"""Tests for StreamSubscription initialization and configuration.

This module tests the initialization process, configuration validation,
and subscription setup without mocks.
"""

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils import fqn


class User(BaseAggregate):
    """User aggregate for initialization tests."""

    user_id = Identifier(identifier=True)
    email = String()
    name = String()


class UserRegistered(BaseEvent):
    """Test event for initialization tests."""

    user_id = Identifier(required=True)
    email = String()
    name = String()


class SendWelcomeEmail(BaseCommand):
    """Test command for initialization tests."""

    user_id = Identifier(required=True)
    email = String()


class UserEventHandler(BaseEventHandler):
    """Test event handler for user events."""

    @handle(UserRegistered)
    def handle_user_registered(self, event):
        pass


class EmailCommandHandler(BaseCommandHandler):
    """Test command handler for email commands."""

    @handle(SendWelcomeEmail)
    def handle_send_welcome_email(self, command):
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    """Register domain elements for testing."""
    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(SendWelcomeEmail, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(EmailCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    """Create test engine."""
    with test_domain.domain_context():
        return Engine(test_domain, test_mode=True)


# Test StreamSubscription Initialization
@pytest.mark.redis
def test_subscription_creation_with_event_handler(test_domain, engine):
    """Test creating subscription with event handler."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Verify basic attributes
        assert subscription.handler == UserEventHandler
        assert subscription.stream_category == "user"
        assert subscription.subscriber_name == fqn(UserEventHandler)
        assert subscription.subscriber_class_name == "UserEventHandler"
        assert subscription.consumer_group == fqn(UserEventHandler)
        assert subscription.dlq_stream == "user:dlq"

        # Verify subscription ID format
        assert "UserEventHandler" in subscription.subscription_id
        # ID should have at least 4 parts (name, hostname (may have hyphens), pid, random)
        assert len(subscription.subscription_id.split("-")) >= 4


@pytest.mark.redis
def test_subscription_creation_with_command_handler(test_domain, engine):
    """Test creating subscription with command handler."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="email", handler=EmailCommandHandler
        )

        # Verify basic attributes
        assert subscription.handler == EmailCommandHandler
        assert subscription.stream_category == "email"
        assert subscription.subscriber_name == fqn(EmailCommandHandler)
        assert subscription.subscriber_class_name == "EmailCommandHandler"
        assert subscription.consumer_group == fqn(EmailCommandHandler)
        assert subscription.dlq_stream == "email:dlq"


@pytest.mark.redis
async def test_successful_initialization(test_domain, engine):
    """Test successful initialization process."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Initially broker should be None
        assert subscription.broker is None

        # Initialize subscription
        await subscription.initialize()

        # After initialization, broker should be set
        assert subscription.broker is not None
        assert subscription.broker == test_domain.brokers.get("default")


@pytest.mark.redis
async def test_initialization_fails_without_default_broker(test_domain, engine):
    """Test initialization fails when no default broker is configured."""
    with test_domain.domain_context():
        # Store and remove default broker
        original_broker = test_domain.brokers.get("default")
        if "default" in test_domain.brokers._brokers:
            del test_domain.brokers._brokers["default"]

        try:
            subscription = StreamSubscription(
                engine=engine, stream_category="user", handler=UserEventHandler
            )

            # Should raise RuntimeError for missing broker
            with pytest.raises(RuntimeError, match="No default broker configured"):
                await subscription.initialize()
        finally:
            # Restore broker
            if original_broker:
                test_domain.brokers._brokers["default"] = original_broker


# Test StreamSubscription Configuration
@pytest.mark.redis
def test_default_configuration_values(test_domain, engine):
    """Test that default configuration values are properly set from domain config."""
    with test_domain.domain_context():
        # Get expected values from config
        server_config = test_domain.config.get("server", {})
        stream_config = server_config.get("stream_subscription", {})

        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Verify values come from config
        assert subscription.messages_per_tick == server_config.get(
            "messages_per_tick", 10
        )
        assert subscription.blocking_timeout_ms == stream_config.get(
            "blocking_timeout_ms", 5000
        )
        assert subscription.max_retries == stream_config.get("max_retries", 3)
        assert subscription.retry_delay_seconds == stream_config.get(
            "retry_delay_seconds", 1
        )
        assert subscription.enable_dlq == stream_config.get("enable_dlq", True)


@pytest.mark.redis
def test_custom_configuration_values(test_domain, engine):
    """Test creating subscription with custom configuration values."""
    with test_domain.domain_context():
        custom_config = {
            "messages_per_tick": 5,
            "blocking_timeout_ms": 2000,
            "max_retries": 5,
            "retry_delay_seconds": 2,
            "enable_dlq": False,
        }

        subscription = StreamSubscription(
            engine=engine,
            stream_category="user",
            handler=UserEventHandler,
            **custom_config,
        )

        # Verify custom values
        assert subscription.messages_per_tick == 5
        assert subscription.blocking_timeout_ms == 2000
        assert subscription.max_retries == 5
        assert subscription.retry_delay_seconds == 2
        assert subscription.enable_dlq is False


@pytest.mark.redis
def test_config_values_from_domain_toml(test_domain, engine):
    """Test that values from domain.toml are properly used."""
    with test_domain.domain_context():
        # The test domain loads from domain.toml which has:
        # blocking_timeout_ms = 100
        # max_retries = 2
        # retry_delay_seconds = 0.001

        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Verify values from domain.toml
        assert subscription.messages_per_tick == 5  # From domain.toml
        assert subscription.blocking_timeout_ms == 100  # From domain.toml
        assert subscription.max_retries == 2  # From domain.toml
        assert subscription.retry_delay_seconds == 0.001  # From domain.toml
        assert subscription.enable_dlq is True  # From domain.toml


@pytest.mark.redis
def test_consumer_naming_consistency(test_domain, engine):
    """Test that consumer names and groups are consistent."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Consumer name should be same as subscription ID
        assert subscription.consumer_name == subscription.subscription_id

        # Consumer group should be same as subscriber name (FQN)
        assert subscription.consumer_group == subscription.subscriber_name
        assert subscription.consumer_group == fqn(UserEventHandler)


@pytest.mark.redis
def test_dlq_stream_naming(test_domain, engine):
    """Test DLQ stream naming convention."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user_events", handler=UserEventHandler
        )

        # DLQ stream should follow naming convention
        assert subscription.dlq_stream == "user_events:dlq"


@pytest.mark.redis
def test_tick_interval_set_to_zero_for_blocking_reads(test_domain, engine):
    """Test that tick_interval is set to 0 for blocking reads."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Tick interval should be 0 for blocking reads
        assert subscription.tick_interval == 0


# Test Subscription Identity Generation
@pytest.mark.redis
def test_subscription_id_includes_required_components(test_domain, engine):
    """Test that subscription ID includes all required components."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Parse subscription ID
        parts = subscription.subscription_id.split("-")

        # Should have at least 4 parts: class_name, hostname (may have hyphens), pid, random
        assert len(parts) >= 4
        assert parts[0] == "UserEventHandler"
        # Last two parts should be pid and random (non-empty)
        assert parts[-1]  # random part
        assert parts[-2]  # pid part


@pytest.mark.redis
def test_multiple_subscriptions_have_unique_ids(test_domain, engine):
    """Test that multiple subscriptions have unique IDs."""
    with test_domain.domain_context():
        # Create multiple subscriptions
        subscriptions = [
            StreamSubscription(
                engine=engine, stream_category=f"user_{i}", handler=UserEventHandler
            )
            for i in range(5)
        ]

        # All IDs should be unique
        ids = [sub.subscription_id for sub in subscriptions]
        assert len(set(ids)) == len(ids)  # No duplicates


@pytest.mark.redis
def test_subscription_names_derived_from_handler(test_domain, engine):
    """Test that subscription names are properly derived from handler."""
    with test_domain.domain_context():
        # Test with event handler
        event_subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Test with command handler
        command_subscription = StreamSubscription(
            engine=engine, stream_category="email", handler=EmailCommandHandler
        )

        # Verify subscriber names use FQN
        assert event_subscription.subscriber_name == fqn(UserEventHandler)
        assert command_subscription.subscriber_name == fqn(EmailCommandHandler)

        # Verify class names
        assert event_subscription.subscriber_class_name == "UserEventHandler"
        assert command_subscription.subscriber_class_name == "EmailCommandHandler"


# Test Cleanup Behavior
@pytest.mark.redis
async def test_cleanup_clears_retry_counts(test_domain, engine):
    """Test that cleanup properly clears retry counts."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="user", handler=UserEventHandler
        )

        # Add some retry counts
        subscription.retry_counts["msg-1"] = 2
        subscription.retry_counts["msg-2"] = 1

        assert len(subscription.retry_counts) == 2

        # Cleanup should clear retry counts
        await subscription.cleanup()

        assert len(subscription.retry_counts) == 0
