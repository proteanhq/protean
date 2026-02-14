"""Tests for Engine subscription integration with SubscriptionFactory.

This module contains comprehensive tests for the integration between
the Engine class and the SubscriptionFactory for automatic subscription
creation and configuration resolution.
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


class RegisterUser(BaseCommand):
    email: String()
    name: String()


def dummy(*args):
    pass


# Test handlers
class UserEventHandler(BaseEventHandler):
    """Basic event handler for testing."""

    @handle(UserRegistered)
    def handle_user_registered(self, event: UserRegistered) -> None:
        dummy(event)


class UserCommandHandler(BaseCommandHandler):
    """Basic command handler for testing."""

    @handle(RegisterUser)
    def handle_register_user(self, command: RegisterUser) -> None:
        dummy(command)


class ProductionEventHandler(BaseEventHandler):
    """Handler with PRODUCTION profile."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class ProjectionHandler(BaseEventHandler):
    """Handler configured for EVENT_STORE subscription."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class CustomConfigHandler(BaseEventHandler):
    """Handler with custom subscription_config."""

    @handle(UserRegistered)
    def handle_event(self, event: UserRegistered) -> None:
        dummy(event)


class TestEngineSubscriptionFactoryIntegration:
    """Tests for Engine integration with SubscriptionFactory."""

    def test_engine_creates_subscription_factory(self, test_domain):
        """Engine should create a SubscriptionFactory instance."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        assert engine._subscription_factory is not None
        assert isinstance(engine._subscription_factory, SubscriptionFactory)

    def test_engine_subscription_factory_property(self, test_domain):
        """Engine should expose subscription_factory property."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        assert engine.subscription_factory is engine._subscription_factory

    def test_engine_factory_has_engine_reference(self, test_domain):
        """SubscriptionFactory should have reference to engine."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        assert engine.subscription_factory.engine is engine


class TestEngineSubscriptionCreation:
    """Tests for Engine automatic subscription creation."""

    def test_creates_subscription_for_event_handler(self, test_domain):
        """Engine should create subscription for registered event handler."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        assert handler_name in engine._subscriptions
        assert engine._subscriptions[handler_name].handler == UserEventHandler

    def test_creates_subscription_for_command_handler(self, test_domain):
        """Engine should create subscription for registered command handler."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(RegisterUser, part_of=User)
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{UserCommandHandler.__module__}.{UserCommandHandler.__qualname__}"
        )
        assert handler_name in engine._subscriptions
        assert engine._subscriptions[handler_name].handler == UserCommandHandler

    def test_creates_multiple_subscriptions(self, test_domain):
        """Engine should create subscriptions for multiple handlers."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(RegisterUser, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        # Should have 2 subscriptions
        assert len(engine._subscriptions) == 2


class TestEngineSubscriptionTypeSelection:
    """Tests for subscription type selection via configuration."""

    def test_uses_server_default_subscription_type_stream(self, test_domain):
        """Engine should create StreamSubscription when server default is stream."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        assert isinstance(subscription, StreamSubscription)

    def test_uses_server_default_subscription_type_event_store(self, test_domain):
        """Engine should create EventStoreSubscription when server default is event_store."""
        test_domain.config["server"]["default_subscription_type"] = "event_store"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        assert isinstance(subscription, EventStoreSubscription)

    def test_handler_subscription_type_overrides_server_default(self, test_domain):
        """Handler's subscription_type should override server default."""
        # Server default is stream
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        # Register handler with EVENT_STORE subscription type
        test_domain.register(
            ProjectionHandler,
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{ProjectionHandler.__module__}.{ProjectionHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        # Should be EventStoreSubscription despite server default being stream
        assert isinstance(subscription, EventStoreSubscription)


class TestEngineSubscriptionProfile:
    """Tests for subscription profile support."""

    def test_uses_handler_subscription_profile(self, test_domain):
        """Engine should use handler's subscription_profile."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            ProductionEventHandler,
            part_of=User,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{ProductionEventHandler.__module__}.{ProductionEventHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        # PRODUCTION profile settings
        assert subscription.messages_per_tick == 100
        assert subscription.max_retries == 3

    def test_uses_server_default_subscription_profile(self, test_domain):
        """Engine should use server default_subscription_profile when handler has none."""
        # Reset server config to only have what we want
        test_domain.config["server"] = {
            "default_subscription_type": "stream",
            "default_subscription_profile": "batch",
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        # BATCH profile settings
        assert subscription.messages_per_tick == 500


class TestEngineSubscriptionConfig:
    """Tests for custom subscription_config support."""

    def test_uses_handler_subscription_config(self, test_domain):
        """Engine should use handler's subscription_config."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            CustomConfigHandler,
            part_of=User,
            subscription_config={
                "messages_per_tick": 75,
                "max_retries": 10,
            },
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{CustomConfigHandler.__module__}.{CustomConfigHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        assert subscription.messages_per_tick == 75
        assert subscription.max_retries == 10


class TestEngineStreamCategoryInference:
    """Tests for stream category inference."""

    def test_infers_stream_category_from_part_of(self, test_domain):
        """Engine should infer stream category from handler's part_of aggregate."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        # Stream category should be inferred from User aggregate
        assert subscription.stream_category == User.meta_.stream_category

    def test_uses_explicit_stream_category(self, test_domain):
        """Engine should use handler's explicit stream_category."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            ProjectionHandler,
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{ProjectionHandler.__module__}.{ProjectionHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        # Should use explicit stream_category
        assert subscription.stream_category == "$all"


class TestEngineInferStreamCategory:
    """Tests for _infer_stream_category method."""

    def test_infer_stream_category_from_explicit(self, test_domain):
        """Should return explicit stream_category from handler Meta."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            ProjectionHandler,
            stream_category="custom-stream",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        stream_category = engine._infer_stream_category(ProjectionHandler)

        assert stream_category == "custom-stream"

    def test_infer_stream_category_from_part_of(self, test_domain):
        """Should infer stream_category from part_of aggregate."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        stream_category = engine._infer_stream_category(UserEventHandler)

        assert stream_category == User.meta_.stream_category

    def test_infer_stream_category_raises_when_cannot_infer(self, test_domain):
        """Should raise ValueError when stream category cannot be inferred."""

        # Create a handler without part_of or stream_category
        class OrphanHandler(BaseEventHandler):
            @handle(UserRegistered)
            def handle_event(self, event: UserRegistered) -> None:
                pass

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        # OrphanHandler has meta_ but no stream_category or part_of
        with pytest.raises(ValueError, match="Cannot infer stream category"):
            engine._infer_stream_category(OrphanHandler)

    def test_infer_stream_category_raises_when_no_meta(self, test_domain):
        """Should raise ValueError when handler has no meta_ attribute."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        class NoMetaHandler:
            pass

        with pytest.raises(ValueError, match="has no meta_ attribute"):
            engine._infer_stream_category(NoMetaHandler)

    def test_infer_stream_category_from_part_of_aggregate_meta(self, test_domain):
        """Should infer stream_category from part_of aggregate's meta_ when handler has no explicit stream_category."""
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        # Create a mock handler with meta_ that has no stream_category but has part_of
        class MockHandlerMeta:
            stream_category = None
            part_of = User

        class MockHandler:
            __name__ = "MockHandler"
            meta_ = MockHandlerMeta()

        result = engine._infer_stream_category(MockHandler)
        assert result == User.meta_.stream_category


class TestEngineSubscriptionAttributes:
    """Tests for subscription attributes set by engine."""

    def test_subscription_has_correct_engine_reference(self, test_domain):
        """Subscription should have correct engine reference."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        assert subscription.engine is engine

    def test_subscription_has_correct_handler_reference(self, test_domain):
        """Subscription should have correct handler reference."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        assert subscription.handler == UserEventHandler

    def test_subscription_has_correct_stream_category(self, test_domain):
        """Subscription should have correct stream category."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = f"{UserEventHandler.__module__}.{UserEventHandler.__qualname__}"
        subscription = engine._subscriptions[handler_name]

        assert subscription.stream_category == User.meta_.stream_category


class TestEngineConfigPriority:
    """Tests for configuration priority hierarchy."""

    def test_handler_config_overrides_server_config(self, test_domain):
        """Handler subscription_config should override server config."""
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.config["server"]["messages_per_tick"] = 200

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            CustomConfigHandler,
            part_of=User,
            subscription_config={"messages_per_tick": 50},
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{CustomConfigHandler.__module__}.{CustomConfigHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        # Handler config (50) should override server config (200)
        assert subscription.messages_per_tick == 50

    def test_handler_profile_overrides_server_profile(self, test_domain):
        """Handler subscription_profile should override server default_subscription_profile."""
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.config["server"]["default_subscription_profile"] = "batch"  # 500

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            ProductionEventHandler,
            part_of=User,
            subscription_profile=SubscriptionProfile.FAST,  # 10
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{ProductionEventHandler.__module__}.{ProductionEventHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        # Handler FAST profile (10) should override server BATCH profile (500)
        assert subscription.messages_per_tick == 10

    def test_full_config_priority_chain(self, test_domain):
        """Full priority chain should be respected."""
        # Server config with profile
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.config["server"]["default_subscription_profile"] = "batch"  # 500

        # Handler-specific server config
        test_domain.config["server"]["subscriptions"] = {
            "CustomConfigHandler": {"messages_per_tick": 300}
        }

        test_domain.register(User, is_event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        # Handler with profile + config override
        test_domain.register(
            CustomConfigHandler,
            part_of=User,
            subscription_profile=SubscriptionProfile.PRODUCTION,  # 100
            subscription_config={"messages_per_tick": 50},  # Override to 50
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        handler_name = (
            f"{CustomConfigHandler.__module__}.{CustomConfigHandler.__qualname__}"
        )
        subscription = engine._subscriptions[handler_name]

        # Handler Meta config (50) > Handler Meta profile (100) > Server handler (300) > Server profile (500)
        assert subscription.messages_per_tick == 50
