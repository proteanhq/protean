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
    email: String()
    name: String()


class UserRegistered(BaseEvent):
    id: Identifier()
    email: String()
    name: String()


class RegisterUser(BaseCommand):
    email: String()
    name: String()


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

    test_domain.register(User, event_sourced=True)
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

    def test_factory_holds_engine_and_config_resolver(self, engine):
        """Factory keeps the engine and builds a ConfigResolver for its domain."""
        factory = SubscriptionFactory(engine)

        assert factory.engine is engine
        assert factory.config_resolver is not None
        assert factory.config_resolver._domain is engine.domain


class TestSubscriptionFactoryCreateStreamSubscription:
    """Tests for creating StreamSubscription instances."""

    @pytest.mark.parametrize(
        "handler, stream_category",
        [
            (UserEventHandler, "my-app::domain-events:v2"),
            (UserCommandHandler, "commands"),
        ],
    )
    def test_creates_stream_subscription_by_default(
        self, factory, handler, stream_category
    ):
        """Factory creates a StreamSubscription by default and wires its attributes."""
        subscription = factory.create_subscription(
            handler=handler,
            stream_category=stream_category,
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.stream_category == stream_category
        assert subscription.handler == handler
        assert subscription.engine is factory.engine
        assert handler.__name__ in subscription.subscriber_name

    @pytest.mark.parametrize(
        "handler, expected",
        [
            (
                ProductionHandler,
                {
                    "messages_per_tick": 100,
                    "blocking_timeout_ms": 5000,
                    "max_retries": 3,
                    "enable_dlq": True,
                },
            ),
            (
                FastHandler,
                {
                    "messages_per_tick": 10,
                    "blocking_timeout_ms": 100,
                    "max_retries": 2,
                    "retry_delay_seconds": 0,
                },
            ),
            (
                BatchHandler,
                {
                    "messages_per_tick": 500,
                    "blocking_timeout_ms": 10000,
                    "max_retries": 5,
                },
            ),
            (
                CustomConfigHandler,
                {"messages_per_tick": 75, "max_retries": 10, "enable_dlq": False},
            ),
            (
                ProfileWithOverridesHandler,
                # Override value, then a value kept from the PRODUCTION profile
                {"messages_per_tick": 50, "blocking_timeout_ms": 5000},
            ),
        ],
    )
    def test_creates_stream_subscription_with_handler_settings(
        self, factory, handler, expected
    ):
        """Factory applies the profile and config each handler registered with."""
        subscription = factory.create_subscription(
            handler=handler,
            stream_category="orders",
        )

        assert isinstance(subscription, StreamSubscription)
        for attr, value in expected.items():
            assert getattr(subscription, attr) == value


class TestSubscriptionFactoryCreateEventStoreSubscription:
    """Tests for creating EventStoreSubscription instances."""

    def test_creates_event_store_subscription_when_configured(self, factory):
        """Factory creates an EventStoreSubscription when subscription_type is EVENT_STORE."""
        subscription = factory.create_subscription(
            handler=ProjectionHandler,
            stream_category="$all",
        )

        assert isinstance(subscription, EventStoreSubscription)
        assert subscription.stream_category == "$all"
        assert subscription.handler == ProjectionHandler
        # EventStoreSubscription uses position tracking, not DLQ
        assert subscription.position_update_interval > 0


class TestSubscriptionFactoryWithServerConfig:
    """Tests for factory behavior with server configuration."""

    def test_uses_server_default_subscription_type(self, test_domain):
        """Factory should use server-level default_subscription_type."""
        test_domain.config["server"] = {
            "default_subscription_type": "event_store",
        }

        test_domain.register(User, event_sourced=True)
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

        test_domain.register(User, event_sourced=True)
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

        test_domain.register(User, event_sourced=True)
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

        test_domain.register(User, event_sourced=True)
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

    def test_logs_resolved_configuration(self, factory, caplog):
        """Factory should log resolved configuration details at DEBUG level."""
        import logging

        with caplog.at_level(
            logging.DEBUG, logger="protean.server.subscription.factory"
        ):
            factory.create_subscription(
                handler=ProductionHandler,
                stream_category="orders",
            )

        # DEBUG log includes subscription type and stream
        assert "Created StreamSubscription" in caplog.text
        assert "ProductionHandler" in caplog.text


class TestSubscriptionFactoryAttributes:
    """Tests for subscription attributes set by factory."""

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


class TestSubscriptionFactoryConfigResolution:
    """Tests for config resolution integration."""

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

        test_domain.register(User, event_sourced=True)
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
