"""Tests for subscription from_config() methods.

This module contains comprehensive tests for the from_config() factory methods
on StreamSubscription and EventStoreSubscription classes.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
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
    test_domain.register(User, event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(RegisterUser, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)

    return Engine(test_domain, test_mode=True)


class TestStreamSubscriptionFromConfig:
    """Tests for StreamSubscription.from_config() method."""

    @pytest.mark.parametrize(
        "profile, expected",
        [
            (
                SubscriptionProfile.PRODUCTION,
                {
                    "messages_per_tick": 100,
                    "blocking_timeout_ms": 5000,
                    "max_retries": 3,
                    "retry_delay_seconds": 1,
                    "enable_dlq": True,
                },
            ),
            (
                SubscriptionProfile.FAST,
                {
                    "messages_per_tick": 10,
                    "blocking_timeout_ms": 100,
                    "max_retries": 2,
                    "retry_delay_seconds": 0,
                },
            ),
            (
                SubscriptionProfile.BATCH,
                {
                    "messages_per_tick": 500,
                    "blocking_timeout_ms": 10000,
                    "max_retries": 5,
                    "retry_delay_seconds": 2,
                    "enable_dlq": True,
                },
            ),
            (
                SubscriptionProfile.DEBUG,
                {
                    "messages_per_tick": 1,
                    "max_retries": 1,
                    "retry_delay_seconds": 0,
                    "enable_dlq": False,
                },
            ),
        ],
    )
    def test_from_config_applies_profile_values(self, engine, profile, expected):
        """StreamSubscription takes its settings from each STREAM-type profile."""
        config = SubscriptionConfig.from_profile(profile)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category="test::user",
            handler=UserEventHandler,
            config=config,
        )

        assert isinstance(subscription, StreamSubscription)
        assert subscription.stream_category == "test::user"
        for attr, value in expected.items():
            assert getattr(subscription, attr) == value

    @pytest.mark.parametrize(
        "handler, stream_category",
        [
            (UserEventHandler, "my-app::domain-events"),
            (UserCommandHandler, "commands"),
        ],
    )
    def test_from_config_sets_engine_handler_and_subscriber(
        self, engine, handler, stream_category
    ):
        """StreamSubscription.from_config wires the engine, handler, stream and subscriber names."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)

        subscription = StreamSubscription.from_config(
            engine=engine,
            stream_category=stream_category,
            handler=handler,
            config=config,
        )

        assert subscription.engine is engine
        assert subscription.handler == handler
        assert subscription.stream_category == stream_category
        assert handler.__name__ in subscription.subscriber_name
        assert subscription.subscriber_class_name == handler.__name__

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

    @pytest.mark.parametrize(
        "config",
        [
            SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION),
            SubscriptionConfig.from_dict(
                {"subscription_type": "event_store", "enable_dlq": False}
            ),
        ],
        ids=["projection_profile", "manual_event_store_type"],
    )
    def test_from_config_rejects_event_store_type(self, engine, config):
        """StreamSubscription.from_config raises error for an EVENT_STORE config."""
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


class TestEventStoreSubscriptionFromConfig:
    """Tests for EventStoreSubscription.from_config() method."""

    @pytest.mark.parametrize("handler", [UserEventHandler, UserCommandHandler])
    def test_from_config_with_projection_profile(self, engine, handler):
        """EventStoreSubscription takes PROJECTION values and wires engine, handler and subscriber."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)

        subscription = EventStoreSubscription.from_config(
            engine=engine,
            stream_category="$all",
            handler=handler,
            config=config,
        )

        assert isinstance(subscription, EventStoreSubscription)
        assert subscription.engine is engine
        assert subscription.stream_category == "$all"
        assert subscription.handler == handler
        assert handler.__name__ in subscription.subscriber_name
        assert subscription.subscriber_class_name == handler.__name__
        assert subscription.messages_per_tick == 100
        assert subscription.position_update_interval == 10
        assert subscription.tick_interval == 0
        assert subscription.origin_stream is None
        assert subscription.current_position == -1
        assert subscription.messages_since_last_position_write == 0

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

    @pytest.mark.parametrize(
        "profile", [SubscriptionProfile.PRODUCTION, SubscriptionProfile.FAST]
    )
    def test_from_config_rejects_stream_type(self, engine, profile):
        """EventStoreSubscription.from_config raises error for a STREAM-type profile."""
        config = SubscriptionConfig.from_profile(profile)

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


class TestFromConfigSubscriptionId:
    """from_config gives every subscription its own id."""

    @pytest.mark.parametrize(
        "subscription_cls, profile",
        [
            (StreamSubscription, SubscriptionProfile.PRODUCTION),
            (EventStoreSubscription, SubscriptionProfile.PROJECTION),
        ],
    )
    def test_from_config_generates_unique_subscription_id(
        self, engine, subscription_cls, profile
    ):
        """Two subscriptions built from one config get different ids naming the handler."""
        config = SubscriptionConfig.from_profile(profile)

        sub1 = subscription_cls.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )
        sub2 = subscription_cls.from_config(
            engine=engine,
            stream_category="test",
            handler=UserEventHandler,
            config=config,
        )

        assert sub1.subscription_id != sub2.subscription_id
        assert "UserEventHandler" in sub1.subscription_id


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

    def test_zero_blocking_timeout_is_rejected(self, engine):
        """A zero blocking_timeout_ms would spin the poll loop, so both the
        config and the constructor called without a config reject it."""
        with pytest.raises(ConfigurationError, match="must be positive"):
            SubscriptionConfig.from_profile(
                SubscriptionProfile.PRODUCTION,
                blocking_timeout_ms=0,
            )

        with pytest.raises(ConfigurationError, match="must be positive"):
            StreamSubscription(
                engine=engine,
                stream_category="test",
                handler=UserEventHandler,
                blocking_timeout_ms=0,
            )

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
