"""Tests for SubscriptionFactory.

This module contains comprehensive tests for the SubscriptionFactory class
which creates subscription instances with automatic type selection.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.server.subscription.factory import SubscriptionFactory
from protean.server.subscription.profiles import SubscriptionProfile, SubscriptionType
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.mixins import handle


# Test domain elements
class User(BaseAggregate):
    email = String()
    name = String()


class UserRegistered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class RegisterUser(BaseCommand):
    email = String()
    name = String()


def dummy(*args):
    pass


# Base handler classes - subscription options passed via register()
class UserEventHandler(BaseEventHandler):
    @handle(UserRegistered)
    def handle_user_registered(self, event: UserRegistered) -> None:
        dummy(event)


class UserCommandHandler(BaseCommandHandler):
    @handle(RegisterUser)
    def handle_register_user(self, command: RegisterUser) -> None:
        dummy(command)


class ProductionHandler(BaseEventHandler):
    """Handler configured with PRODUCTION profile via register()."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class ProjectionHandler(BaseEventHandler):
    """Handler configured for projections (EVENT_STORE type) via register()."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class FastHandler(BaseEventHandler):
    """Handler configured with FAST profile via register()."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class BatchHandler(BaseEventHandler):
    """Handler configured with BATCH profile via register()."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class CustomConfigHandler(BaseEventHandler):
    """Handler with custom subscription_config via register()."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class ProfileWithOverridesHandler(BaseEventHandler):
    """Handler with profile and additional overrides via register()."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


@pytest.fixture
def engine(test_domain):
    """Create an engine for testing with handlers configured via register()."""
    # Set default subscription type to STREAM for testing default behavior
    test_domain.config["server"]["default_subscription_type"] = "stream"

    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(RegisterUser, part_of=User)

    # Register handlers with subscription options via register()
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(
        ProductionHandler,
        part_of=User,
        subscription_profile=SubscriptionProfile.PRODUCTION,
    )
    test_domain.register(
        ProjectionHandler,
        stream_category="$all",
        subscription_type=SubscriptionType.EVENT_STORE,
    )
    test_domain.register(
        FastHandler,
        part_of=User,
        subscription_profile=SubscriptionProfile.FAST,
    )
    test_domain.register(
        BatchHandler,
        part_of=User,
        subscription_profile=SubscriptionProfile.BATCH,
    )
    test_domain.register(
        CustomConfigHandler,
        part_of=User,
        subscription_config={
            "messages_per_tick": 75,
            "max_retries": 10,
            "enable_dlq": False,
        },
    )
    test_domain.register(
        ProfileWithOverridesHandler,
        part_of=User,
        subscription_profile=SubscriptionProfile.PRODUCTION,
        subscription_config={"messages_per_tick": 50},
    )
    test_domain.init(traverse=False)

    return Engine(test_domain, test_mode=True)


@pytest.fixture
def factory(engine):
    """Create a SubscriptionFactory instance."""
    return SubscriptionFactory(engine)


class TestSubscriptionFactoryInitialization:
    """Tests for SubscriptionFactory initialization."""

    def test_factory_initializes_with_engine(self, engine):
        """Factory should initialize with an engine reference."""
        factory = SubscriptionFactory(engine)

        assert factory.engine is engine

    def test_factory_creates_config_resolver(self, engine):
        """Factory should create a ConfigResolver instance."""
        factory = SubscriptionFactory(engine)

        assert factory.config_resolver is not None
        assert factory.config_resolver._domain is engine.domain


class TestSubscriptionFactoryCreateStreamSubscription:
    """Tests for creating StreamSubscription instances."""

    def test_creates_stream_subscription_by_default(self, factory):
        """Factory should create StreamSubscription by default."""
        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test::user",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.stream_category == "test::user"
        assert subscription.handler == UserEventHandler

    def test_creates_stream_subscription_with_production_profile(self, factory):
        """Factory should create StreamSubscription with PRODUCTION profile settings."""
        subscription = factory.create_subscription(
            handler=ProductionHandler,
            stream_category="orders",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.messages_per_tick == 100
        assert subscription.blocking_timeout_ms == 5000
        assert subscription.max_retries == 3
        assert subscription.enable_dlq is True

    def test_creates_stream_subscription_with_fast_profile(self, factory):
        """Factory should create StreamSubscription with FAST profile settings."""
        subscription = factory.create_subscription(
            handler=FastHandler,
            stream_category="notifications",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.messages_per_tick == 10
        assert subscription.blocking_timeout_ms == 100
        assert subscription.max_retries == 2
        assert subscription.retry_delay_seconds == 0

    def test_creates_stream_subscription_with_batch_profile(self, factory):
        """Factory should create StreamSubscription with BATCH profile settings."""
        subscription = factory.create_subscription(
            handler=BatchHandler,
            stream_category="reports",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.messages_per_tick == 500
        assert subscription.blocking_timeout_ms == 10000
        assert subscription.max_retries == 5

    def test_creates_stream_subscription_with_custom_config(self, factory):
        """Factory should create StreamSubscription with custom config."""
        subscription = factory.create_subscription(
            handler=CustomConfigHandler,
            stream_category="custom",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.messages_per_tick == 75
        assert subscription.max_retries == 10
        assert subscription.enable_dlq is False

    def test_creates_stream_subscription_with_profile_overrides(self, factory):
        """Factory should apply overrides on top of profile."""
        subscription = factory.create_subscription(
            handler=ProfileWithOverridesHandler,
            stream_category="mixed",
        )

        assert isinstance(subscription, StreamSubscription)
        # Override value
        assert subscription.messages_per_tick == 50
        # Profile default
        assert subscription.blocking_timeout_ms == 5000

    def test_creates_stream_subscription_for_command_handler(self, factory):
        """Factory should create StreamSubscription for command handlers."""
        subscription = factory.create_subscription(
            handler=UserCommandHandler,
            stream_category="commands",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.handler == UserCommandHandler


class TestSubscriptionFactoryCreateEventStoreSubscription:
    """Tests for creating EventStoreSubscription instances."""

    def test_creates_event_store_subscription_when_configured(self, factory):
        """Factory should create EventStoreSubscription when subscription_type is EVENT_STORE."""
        subscription = factory.create_subscription(
            handler=ProjectionHandler,
            stream_category="$all",
        )

        assert isinstance(subscription, EventStoreSubscription)
        assert subscription.stream_category == "$all"
        assert subscription.handler == ProjectionHandler

    def test_event_store_subscription_has_correct_settings(self, factory):
        """EventStoreSubscription should have correct default settings."""
        subscription = factory.create_subscription(
            handler=ProjectionHandler,
            stream_category="events",
        )

        assert isinstance(subscription, EventStoreSubscription)
        # EventStoreSubscription uses position tracking, not DLQ
        assert subscription.position_update_interval > 0


class TestSubscriptionFactoryWithServerConfig:
    """Tests for factory behavior with server configuration."""

    def test_uses_server_default_subscription_type(self, test_domain):
        """Factory should use server-level default_subscription_type."""
        test_domain.config["server"] = {
            "default_subscription_type": "event_store",
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        factory = SubscriptionFactory(engine)

        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert isinstance(subscription, EventStoreSubscription)

    def test_uses_server_default_subscription_profile(self, test_domain):
        """Factory should use server-level default_subscription_profile."""
        test_domain.config["server"] = {
            "default_subscription_profile": "batch",
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        factory = SubscriptionFactory(engine)

        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.messages_per_tick == 500  # BATCH profile

    def test_uses_server_stream_subscription_settings(self, test_domain):
        """Factory should use server-level stream_subscription settings."""
        test_domain.config["server"] = {
            "stream_subscription": {
                "blocking_timeout_ms": 2000,
                "max_retries": 7,
            }
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        factory = SubscriptionFactory(engine)

        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.blocking_timeout_ms == 2000
        assert subscription.max_retries == 7

    def test_handler_meta_overrides_server_config(self, test_domain):
        """Handler Meta should override server-level config."""
        test_domain.config["server"] = {
            "default_subscription_type": "stream",
            "messages_per_tick": 200,
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        # Register with explicit subscription_type to override server config
        test_domain.register(
            ProjectionHandler,
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        factory = SubscriptionFactory(engine)

        subscription = factory.create_subscription(
            handler=ProjectionHandler,
            stream_category="$all",
        )

        # Handler Meta overrides server config
        assert isinstance(subscription, EventStoreSubscription)


class TestSubscriptionFactoryLogging:
    """Tests for factory logging behavior."""

    def test_logs_subscription_creation(self, factory, caplog):
        """Factory should log subscription creation."""
        import logging

        with caplog.at_level(logging.INFO):
            factory.create_subscription(
                handler=UserEventHandler,
                stream_category="test",
            )

        assert "Created" in caplog.text
        assert "UserEventHandler" in caplog.text

    def test_logs_resolved_configuration(self, factory, caplog):
        """Factory should log resolved configuration details at INFO level."""
        import logging

        with caplog.at_level(logging.INFO):
            factory.create_subscription(
                handler=ProductionHandler,
                stream_category="orders",
            )

        # INFO log includes subscription type and stream
        assert "Created StreamSubscription" in caplog.text
        assert "ProductionHandler" in caplog.text

    def test_logs_subscription_type_in_info(self, factory, caplog):
        """Factory should log subscription type at INFO level."""
        import logging

        with caplog.at_level(logging.INFO):
            factory.create_subscription(
                handler=ProductionHandler,
                stream_category="test",
            )

        assert "Created StreamSubscription" in caplog.text


class TestSubscriptionFactoryAttributes:
    """Tests for subscription attributes set by factory."""

    def test_sets_correct_stream_category(self, factory):
        """Factory should set correct stream_category on subscription."""
        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="my-app::events",
        )

        assert subscription.stream_category == "my-app::events"

    def test_sets_correct_handler_reference(self, factory):
        """Factory should set correct handler reference on subscription."""
        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert subscription.handler == UserEventHandler

    def test_sets_correct_engine_reference(self, factory):
        """Factory should set correct engine reference on subscription."""
        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert subscription.engine is factory.engine

    def test_generates_unique_subscription_id(self, factory):
        """Factory should generate unique subscription IDs."""
        sub1 = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )
        sub2 = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert sub1.subscription_id != sub2.subscription_id

    def test_sets_subscriber_name_from_handler(self, factory):
        """Factory should set subscriber_name from handler."""
        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="test",
        )

        assert "UserEventHandler" in subscription.subscriber_name


class TestSubscriptionFactoryEdgeCases:
    """Edge case tests for SubscriptionFactory."""

    def test_handles_special_stream_category_names(self, factory):
        """Factory should handle special characters in stream category."""
        subscription = factory.create_subscription(
            handler=UserEventHandler,
            stream_category="my-app::domain-events:v2",
        )

        assert subscription.stream_category == "my-app::domain-events:v2"

    def test_handles_all_stream_for_projections(self, factory):
        """Factory should handle $all stream for projections."""
        subscription = factory.create_subscription(
            handler=ProjectionHandler,
            stream_category="$all",
        )

        assert subscription.stream_category == "$all"


class TestSubscriptionFactoryConfigResolution:
    """Tests for config resolution integration."""

    def test_config_resolver_is_accessible(self, factory):
        """Factory should expose config_resolver for inspection."""
        assert factory.config_resolver is not None

    def test_uses_config_resolver_for_resolution(self, factory):
        """Factory should use ConfigResolver for configuration."""
        # Create a subscription and verify the config was properly resolved
        subscription = factory.create_subscription(
            handler=ProductionHandler,
            stream_category="orders",
        )

        # PRODUCTION profile values should be applied
        assert isinstance(subscription, StreamSubscription)
        assert subscription.messages_per_tick == 100
        assert subscription.max_retries == 3
        assert subscription.enable_dlq is True

    def test_priority_chain_is_respected(self, test_domain):
        """Factory should respect the full config priority chain."""
        # Set up server config with defaults
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.config["server"]["default_subscription_profile"] = (
            "batch"  # Would give 500 messages
        )
        test_domain.config["server"]["subscriptions"] = {
            "ProfileWithOverridesHandler": {
                "messages_per_tick": 300,  # Would override to 300
            }
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        # Register handler with subscription_profile and subscription_config
        # These should take highest priority over server config
        test_domain.register(
            ProfileWithOverridesHandler,
            part_of=User,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={"messages_per_tick": 50},
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        factory = SubscriptionFactory(engine)

        subscription = factory.create_subscription(
            handler=ProfileWithOverridesHandler,
            stream_category="test",
        )

        # Handler Meta (50) should override server handler config (300)
        # which would override server default profile BATCH (500)
        assert subscription.messages_per_tick == 50
