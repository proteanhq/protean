"""Tests for event handler subscription configuration options.

This module contains tests for subscription configuration options on event handlers,
including Meta attribute reading, setting via decorator and register(), and
combined usage with stream_category.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.subscription.profiles import (
    SubscriptionProfile,
    SubscriptionType,
)


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    customer_name: String()


class TestEventHandlerSubscriptionDefaults:
    """Tests for default subscription configuration values on event handlers."""

    def test_default_subscription_type_is_none(self, test_domain):
        """Event handler should have None as default subscription_type."""

        @test_domain.event_handler(part_of=Order)
        class OrderEventHandler(BaseEventHandler):
            pass

        assert OrderEventHandler.meta_.subscription_type is None

    def test_default_subscription_profile_is_none(self, test_domain):
        """Event handler should have None as default subscription_profile."""

        @test_domain.event_handler(part_of=Order)
        class OrderEventHandler(BaseEventHandler):
            pass

        assert OrderEventHandler.meta_.subscription_profile is None

    def test_default_subscription_config_is_empty_dict(self, test_domain):
        """Event handler should have empty dict as default subscription_config."""

        @test_domain.event_handler(part_of=Order)
        class OrderEventHandler(BaseEventHandler):
            pass

        assert OrderEventHandler.meta_.subscription_config == {}


class TestEventHandlerSubscriptionTypeOption:
    """Tests for subscription_type option on event handlers."""

    def test_subscription_type_stream_via_decorator(self, test_domain):
        """STREAM subscription type can be set via decorator."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
        )
        class OrderEventHandler(BaseEventHandler):
            pass

        assert OrderEventHandler.meta_.subscription_type == SubscriptionType.STREAM

    def test_subscription_type_event_store_via_decorator(self, test_domain):
        """EVENT_STORE subscription type can be set via decorator."""

        @test_domain.event_handler(
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        class AllEventsHandler(BaseEventHandler):
            pass

        assert AllEventsHandler.meta_.subscription_type == SubscriptionType.EVENT_STORE

    def test_subscription_type_via_register(self, test_domain):
        """Subscription type can be set via domain.register()."""

        class OrderEventHandler(BaseEventHandler):
            pass

        test_domain.register(
            OrderEventHandler,
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
        )
        assert OrderEventHandler.meta_.subscription_type == SubscriptionType.STREAM


class TestEventHandlerSubscriptionProfileOption:
    """Tests for subscription_profile option on event handlers."""

    def test_subscription_profile_production(self, test_domain):
        """PRODUCTION subscription profile can be set."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderEventHandler(BaseEventHandler):
            pass

        assert (
            OrderEventHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )

    def test_subscription_profile_fast(self, test_domain):
        """FAST subscription profile can be set."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.FAST,
        )
        class FastOrderHandler(BaseEventHandler):
            pass

        assert FastOrderHandler.meta_.subscription_profile == SubscriptionProfile.FAST

    def test_subscription_profile_batch(self, test_domain):
        """BATCH subscription profile can be set."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.BATCH,
        )
        class BatchOrderHandler(BaseEventHandler):
            pass

        assert BatchOrderHandler.meta_.subscription_profile == SubscriptionProfile.BATCH

    def test_subscription_profile_debug(self, test_domain):
        """DEBUG subscription profile can be set."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.DEBUG,
        )
        class DebugOrderHandler(BaseEventHandler):
            pass

        assert DebugOrderHandler.meta_.subscription_profile == SubscriptionProfile.DEBUG

    def test_subscription_profile_projection(self, test_domain):
        """PROJECTION subscription profile can be set."""

        @test_domain.event_handler(
            stream_category="$all",
            subscription_profile=SubscriptionProfile.PROJECTION,
        )
        class ProjectionBuilder(BaseEventHandler):
            pass

        assert (
            ProjectionBuilder.meta_.subscription_profile
            == SubscriptionProfile.PROJECTION
        )

    def test_subscription_profile_via_register(self, test_domain):
        """Subscription profile can be set via domain.register()."""

        class OrderEventHandler(BaseEventHandler):
            pass

        test_domain.register(
            OrderEventHandler,
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        assert (
            OrderEventHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )


class TestEventHandlerSubscriptionConfigOption:
    """Tests for subscription_config dict option on event handlers."""

    def test_subscription_config_via_decorator(self, test_domain):
        """Subscription config dict can be set via decorator."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_config={"messages_per_tick": 50, "max_retries": 5},
        )
        class OrderEventHandler(BaseEventHandler):
            pass

        assert OrderEventHandler.meta_.subscription_config == {
            "messages_per_tick": 50,
            "max_retries": 5,
        }

    def test_subscription_config_via_register(self, test_domain):
        """Subscription config can be set via domain.register()."""

        class OrderEventHandler(BaseEventHandler):
            pass

        test_domain.register(
            OrderEventHandler,
            part_of=Order,
            subscription_config={"messages_per_tick": 25},
        )
        assert OrderEventHandler.meta_.subscription_config == {"messages_per_tick": 25}

    def test_subscription_config_with_various_options(self, test_domain):
        """subscription_config can contain various subscription options."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_config={
                "messages_per_tick": 100,
                "tick_interval": 0,
                "blocking_timeout_ms": 5000,
                "max_retries": 3,
                "retry_delay_seconds": 1,
                "enable_dlq": True,
                "position_update_interval": 10,
            },
        )
        class ConfiguredHandler(BaseEventHandler):
            pass

        config = ConfiguredHandler.meta_.subscription_config
        assert config["messages_per_tick"] == 100
        assert config["tick_interval"] == 0
        assert config["blocking_timeout_ms"] == 5000
        assert config["max_retries"] == 3
        assert config["retry_delay_seconds"] == 1
        assert config["enable_dlq"] is True
        assert config["position_update_interval"] == 10

    def test_subscription_config_with_origin_stream(self, test_domain):
        """subscription_config can contain origin_stream filter."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_config={"origin_stream": "inventory"},
        )
        class FilteredHandler(BaseEventHandler):
            pass

        assert FilteredHandler.meta_.subscription_config["origin_stream"] == "inventory"


class TestEventHandlerCombinedSubscriptionOptions:
    """Tests for combining multiple subscription options."""

    def test_all_subscription_options_together(self, test_domain):
        """All subscription options can be set together."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={"messages_per_tick": 100, "enable_dlq": True},
        )
        class OrderEventHandler(BaseEventHandler):
            pass

        assert OrderEventHandler.meta_.subscription_type == SubscriptionType.STREAM
        assert (
            OrderEventHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )
        assert OrderEventHandler.meta_.subscription_config == {
            "messages_per_tick": 100,
            "enable_dlq": True,
        }

    def test_subscription_options_with_explicit_stream_category(self, test_domain):
        """Event handler can have both stream_category and subscription config."""

        @test_domain.event_handler(
            stream_category="custom::orders",
            subscription_profile=SubscriptionProfile.PROJECTION,
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        class CustomStreamHandler(BaseEventHandler):
            pass

        assert CustomStreamHandler.meta_.stream_category == "custom::orders"
        assert (
            CustomStreamHandler.meta_.subscription_profile
            == SubscriptionProfile.PROJECTION
        )
        assert (
            CustomStreamHandler.meta_.subscription_type == SubscriptionType.EVENT_STORE
        )

    def test_subscription_options_with_stream_category_from_part_of(self, test_domain):
        """Event handler derives stream_category from part_of aggregate."""
        test_domain.register(Order)

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderHandler(BaseEventHandler):
            pass

        # stream_category should be derived from Order aggregate
        assert OrderHandler.meta_.stream_category == "test::order"
        assert OrderHandler.meta_.subscription_profile == SubscriptionProfile.PRODUCTION


class TestEventHandlerSubscriptionInheritance:
    """Tests for subscription configuration inheritance behavior."""

    def test_subscription_options_not_inherited_by_subclass(self, test_domain):
        """Subscription options are not automatically inherited by subclasses."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class BaseOrderHandler(BaseEventHandler):
            pass

        # Create a new handler without specifying subscription options
        @test_domain.event_handler(part_of=Order)
        class DerivedOrderHandler(BaseEventHandler):
            pass

        # Base handler should have the profile set
        assert (
            BaseOrderHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )
        # Derived handler should have default (None)
        assert DerivedOrderHandler.meta_.subscription_profile is None


class TestEventHandlerMissingSubscriptionOptions:
    """Tests for handling cases where subscription options are missing or partial."""

    def test_event_handler_without_subscription_options(self, test_domain):
        """Event handler without subscription options gets defaults."""

        @test_domain.event_handler(part_of=Order)
        class SimpleHandler(BaseEventHandler):
            pass

        assert SimpleHandler.meta_.subscription_type is None
        assert SimpleHandler.meta_.subscription_profile is None
        assert SimpleHandler.meta_.subscription_config == {}

    def test_event_handler_with_partial_options(self, test_domain):
        """Event handler with some options leaves others as defaults."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.FAST,
            # subscription_type and subscription_config not specified
        )
        class PartialHandler(BaseEventHandler):
            pass

        assert PartialHandler.meta_.subscription_type is None
        assert PartialHandler.meta_.subscription_profile == SubscriptionProfile.FAST
        assert PartialHandler.meta_.subscription_config == {}
