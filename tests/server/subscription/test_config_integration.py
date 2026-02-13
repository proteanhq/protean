"""Tests for subscription from_config() methods.

This module contains comprehensive tests for the from_config() factory methods
on StreamSubscription and EventStoreSubscription classes.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.server.subscription.profiles import (
    SubscriptionConfig,
    SubscriptionProfile,
)
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


class UserEventHandler(BaseEventHandler):
    @handle(UserRegistered)
    def handle_user_registered(self, event: UserRegistered) -> None:
        dummy(event)


class UserCommandHandler(BaseCommandHandler):
    @handle(RegisterUser)
    def handle_register_user(self, command: RegisterUser) -> None:
        dummy(command)


@pytest.fixture
def engine(test_domain):
    """Create an engine for testing."""
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(RegisterUser, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)

    return Engine(test_domain, test_mode=True)


class TestStreamSubscriptionFromConfig:
    """Tests for StreamSubscription.from_config() method."""

    def test_from_config_with_production_profile(self, engine):
        """StreamSubscription can be created from PRODUCTION profile config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test::user",
            handler=UserEventHandler,
            config=config,
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.stream_category == "test::user"
        assert subscription.handler == UserEventHandler
        assert subscription.messages_per_tick == 100
        assert subscription.blocking_timeout_ms == 5000
        assert subscription.max_retries == 3
        assert subscription.retry_delay_seconds == 1
        assert subscription.enable_dlq is True

    def test_from_config_with_fast_profile(self, engine):
        """StreamSubscription can be created from FAST profile config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.FAST)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="notifications",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 10
        assert subscription.blocking_timeout_ms == 100
        assert subscription.max_retries == 2
        assert subscription.retry_delay_seconds == 0

    def test_from_config_with_batch_profile(self, engine):
        """StreamSubscription can be created from BATCH profile config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.BATCH)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="reports",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 500
        assert subscription.blocking_timeout_ms == 10000
        assert subscription.max_retries == 5
        assert subscription.retry_delay_seconds == 2
        assert subscription.enable_dlq is True

    def test_from_config_with_debug_profile(self, engine):
        """StreamSubscription can be created from DEBUG profile config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.DEBUG)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="debug::events",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 1
        assert subscription.max_retries == 1
        assert subscription.retry_delay_seconds == 0
        assert subscription.enable_dlq is False

    def test_from_config_with_custom_overrides(self, engine):
        """StreamSubscription respects custom overrides on profile."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            messages_per_tick=50,
            max_retries=10,
            enable_dlq=False,
        )

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="custom",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 50
        assert subscription.max_retries == 10
        assert subscription.enable_dlq is False
        # Profile default preserved
        assert subscription.blocking_timeout_ms == 5000

    def test_from_config_with_dict_config(self, engine):
        """StreamSubscription can be created from dict-based config."""
        config = SubscriptionConfig.from_dict(
            {
                "profile": "production",
                "messages_per_tick": 75,
                "blocking_timeout_ms": 3000,
            }
        )

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="orders",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 75
        assert subscription.blocking_timeout_ms == 3000
        assert subscription.max_retries == 3  # Profile default

    def test_from_config_with_command_handler(self, engine):
        """StreamSubscription can be created with a command handler."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="commands",
            handler=UserCommandHandler,
            config=config,
        )

        assert subscription.handler == UserCommandHandler

    def test_from_config_rejects_event_store_type(self, engine):
        """StreamSubscription.from_config raises error for EVENT_STORE config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        with pytest.raises(ConfigurationError) as exc_info:
            StreamSubscription.from_config(
                engine=engine,
                stream_category="projections",
                handler=UserEventHandler,
                config=config,
            )

        assert "Cannot create StreamSubscription" in str(exc_info.value)
        assert "subscription_type=event_store" in str(exc_info.value)
        assert "Expected subscription_type=stream" in str(exc_info.value)

    def test_from_config_rejects_manually_set_event_store_type(self, engine):
        """StreamSubscription.from_config raises error when type is manually set to EVENT_STORE."""
        config = SubscriptionConfig.from_dict(
            {
                "subscription_type": "event_store",
                "enable_dlq": False,  # Required for EVENT_STORE
            }
        )

        with pytest.raises(ConfigurationError) as exc_info:
            StreamSubscription.from_config(
                engine=engine,
                stream_category="test",
                handler=UserEventHandler,
                config=config,
            )

        assert "Cannot create StreamSubscription" in str(exc_info.value)

    def test_from_config_sets_engine_correctly(self, engine):
        """StreamSubscription.from_config sets the engine reference."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.engine is engine

    def test_from_config_generates_unique_subscription_id(self, engine):
        """StreamSubscription.from_config generates a unique subscription ID."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        sub1 = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        sub2 = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert sub1.subscription_id != sub2.subscription_id
        assert "UserEventHandler" in sub1.subscription_id


class TestEventStoreSubscriptionFromConfig:
    """Tests for EventStoreSubscription.from_config() method."""

    def test_from_config_with_projection_profile(self, engine):
        """EventStoreSubscription can be created from PROJECTION profile config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="$all",
            handler=UserEventHandler,
            config=config,
        )

        assert isinstance(subscription, EventStoreSubscription)
        assert subscription.stream_category == "$all"
        assert subscription.handler == UserEventHandler
        assert subscription.messages_per_tick == 100
        assert subscription.position_update_interval == 10
        assert subscription.tick_interval == 0

    def test_from_config_with_custom_overrides(self, engine):
        """EventStoreSubscription respects custom overrides on profile."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PROJECTION,
            messages_per_tick=200,
            position_update_interval=50,
            tick_interval=2,
        )

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="orders",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 200
        assert subscription.position_update_interval == 50
        assert subscription.tick_interval == 2

    def test_from_config_with_origin_stream(self, engine):
        """EventStoreSubscription can be created with origin_stream filter."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PROJECTION,
            origin_stream="orders",
        )

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="$all",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.origin_stream == "orders"

    def test_from_config_with_dict_config(self, engine):
        """EventStoreSubscription can be created from dict-based config."""
        config = SubscriptionConfig.from_dict(
            {
                "subscription_type": "event_store",
                "enable_dlq": False,
                "messages_per_tick": 50,
                "position_update_interval": 25,
                "origin_stream": "users",
            }
        )

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test::events",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.messages_per_tick == 50
        assert subscription.position_update_interval == 25
        assert subscription.origin_stream == "users"

    def test_from_config_with_command_handler(self, engine):
        """EventStoreSubscription can be created with a command handler."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="commands",
            handler=UserCommandHandler,
            config=config,
        )

        assert subscription.handler == UserCommandHandler

    def test_from_config_rejects_stream_type(self, engine):
        """EventStoreSubscription.from_config raises error for STREAM config."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        with pytest.raises(ConfigurationError) as exc_info:
            EventStoreSubscription.from_config(
                engine=engine,
                stream_category="test",
                handler=UserEventHandler,
                config=config,
            )

        assert "Cannot create EventStoreSubscription" in str(exc_info.value)
        assert "subscription_type=stream" in str(exc_info.value)
        assert "Expected subscription_type=event_store" in str(exc_info.value)

    def test_from_config_rejects_fast_profile(self, engine):
        """EventStoreSubscription.from_config raises error for FAST profile (STREAM type)."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.FAST)

        with pytest.raises(ConfigurationError) as exc_info:
            EventStoreSubscription.from_config(
                engine=engine,
                stream_category="test",
                handler=UserEventHandler,
                config=config,
            )

        assert "Cannot create EventStoreSubscription" in str(exc_info.value)

    def test_from_config_sets_engine_correctly(self, engine):
        """EventStoreSubscription.from_config sets the engine reference."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.engine is engine

    def test_from_config_generates_unique_subscription_id(self, engine):
        """EventStoreSubscription.from_config generates a unique subscription ID."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        sub1 = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        sub2 = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert sub1.subscription_id != sub2.subscription_id
        assert "UserEventHandler" in sub1.subscription_id

    def test_from_config_initializes_position_tracking(self, engine):
        """EventStoreSubscription.from_config initializes position tracking attributes."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.current_position == -1
        assert subscription.messages_since_last_position_write == 0


class TestFromConfigRoundtrip:
    """Tests for config roundtrip (to_dict -> from_dict -> from_config)."""

    def test_stream_subscription_config_roundtrip(self, engine):
        """StreamSubscription config can survive a roundtrip through to_dict."""
        original_config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            messages_per_tick=75,
        )

        # Roundtrip through dict
        dict_repr = original_config.to_dict()
        restored_config = SubscriptionConfig.from_dict(dict_repr)

        # Create subscriptions from both
        sub_original = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=original_config,
        )

        sub_restored = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=restored_config,
        )

        # Verify configurations match
        assert sub_original.messages_per_tick == sub_restored.messages_per_tick
        assert sub_original.blocking_timeout_ms == sub_restored.blocking_timeout_ms
        assert sub_original.max_retries == sub_restored.max_retries
        assert sub_original.enable_dlq == sub_restored.enable_dlq

    def test_event_store_subscription_config_roundtrip(self, engine):
        """EventStoreSubscription config can survive a roundtrip through to_dict."""
        original_config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PROJECTION,
            messages_per_tick=200,
            origin_stream="orders",
        )

        # Roundtrip through dict
        dict_repr = original_config.to_dict()
        restored_config = SubscriptionConfig.from_dict(dict_repr)

        # Create subscriptions from both
        sub_original = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=original_config,
        )

        sub_restored = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=restored_config,
        )

        # Verify configurations match
        assert sub_original.messages_per_tick == sub_restored.messages_per_tick
        assert (
            sub_original.position_update_interval
            == sub_restored.position_update_interval
        )
        assert sub_original.origin_stream == sub_restored.origin_stream


class TestFromConfigEdgeCases:
    """Edge case tests for from_config() methods."""

    def test_stream_subscription_with_zero_blocking_timeout(self, engine):
        """StreamSubscription can have zero blocking_timeout_ms."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            blocking_timeout_ms=0,
        )

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.blocking_timeout_ms == 0

    def test_stream_subscription_with_zero_max_retries(self, engine):
        """StreamSubscription can have zero max_retries (no retries)."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            max_retries=0,
        )

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.max_retries == 0

    def test_event_store_subscription_without_origin_stream(self, engine):
        """EventStoreSubscription can be created without origin_stream filter."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="$all",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.origin_stream is None

    def test_stream_subscription_with_special_stream_category(self, engine):
        """StreamSubscription handles special stream category names."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="my-app::domain-events",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.stream_category == "my-app::domain-events"

    def test_event_store_subscription_with_all_stream(self, engine):
        """EventStoreSubscription handles $all stream category."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="$all",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.stream_category == "$all"


class TestFromConfigWithAllProfiles:
    """Test from_config with all available profiles to ensure compatibility."""

    @pytest.mark.parametrize(
        "profile",
        [
            SubscriptionProfile.PRODUCTION,
            SubscriptionProfile.FAST,
            SubscriptionProfile.BATCH,
            SubscriptionProfile.DEBUG,
        ],
    )
    def test_stream_subscription_with_stream_profiles(self, engine, profile):
        """StreamSubscription can be created from all STREAM-type profiles."""
        config = SubscriptionConfig.from_profile(profile)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.stream_category == "test"

    def test_event_store_subscription_with_projection_profile(self, engine):
        """EventStoreSubscription can be created from PROJECTION profile."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="$all",
            handler=UserEventHandler,
            config=config,
        )

        assert isinstance(subscription, EventStoreSubscription)


class TestFromConfigSubscriberAttributes:
    """Tests that from_config correctly sets subscriber attributes."""

    def test_stream_subscription_subscriber_name(self, engine):
        """StreamSubscription.from_config sets correct subscriber_name."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        # subscriber_name should be the FQN of the handler
        assert "UserEventHandler" in subscription.subscriber_name

    def test_stream_subscription_subscriber_class_name(self, engine):
        """StreamSubscription.from_config sets correct subscriber_class_name."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.subscriber_class_name == "UserEventHandler"

    def test_event_store_subscription_subscriber_name(self, engine):
        """EventStoreSubscription.from_config sets correct subscriber_name."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert "UserEventHandler" in subscription.subscriber_name

    def test_event_store_subscription_subscriber_class_name(self, engine):
        """EventStoreSubscription.from_config sets correct subscriber_class_name."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert subscription.subscriber_class_name == "UserEventHandler"
