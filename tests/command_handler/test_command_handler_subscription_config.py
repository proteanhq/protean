"""Tests for command handler subscription configuration options.

This module contains tests for subscription configuration options on command handlers,
including Meta attribute reading, setting via decorator and register(), and
stream_category derivation from aggregate.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server.subscription.profiles import (
    SubscriptionProfile,
    SubscriptionType,
)


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    customer_name: String()


class TestCommandHandlerSubscriptionDefaults:
    """Tests for default subscription configuration values on command handlers."""

    def test_default_subscription_type_is_none(self, test_domain):
        """Command handler should have None as default subscription_type."""

        @test_domain.command_handler(part_of=Order)
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert OrderCommandHandler.meta_.subscription_type is None

    def test_default_subscription_profile_is_none(self, test_domain):
        """Command handler should have None as default subscription_profile."""

        @test_domain.command_handler(part_of=Order)
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert OrderCommandHandler.meta_.subscription_profile is None

    def test_default_subscription_config_is_empty_dict(self, test_domain):
        """Command handler should have empty dict as default subscription_config."""

        @test_domain.command_handler(part_of=Order)
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert OrderCommandHandler.meta_.subscription_config == {}


class TestCommandHandlerSubscriptionTypeOption:
    """Tests for subscription_type option on command handlers."""

    def test_subscription_type_stream_via_decorator(self, test_domain):
        """STREAM subscription type can be set via decorator."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert OrderCommandHandler.meta_.subscription_type == SubscriptionType.STREAM

    def test_subscription_type_event_store_via_decorator(self, test_domain):
        """EVENT_STORE subscription type can be set via decorator."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert (
            OrderCommandHandler.meta_.subscription_type == SubscriptionType.EVENT_STORE
        )

    def test_subscription_type_via_register(self, test_domain):
        """Subscription type can be set via domain.register()."""

        class OrderCommandHandler(BaseCommandHandler):
            pass

        test_domain.register(
            OrderCommandHandler,
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
        )
        assert OrderCommandHandler.meta_.subscription_type == SubscriptionType.STREAM


class TestCommandHandlerSubscriptionProfileOption:
    """Tests for subscription_profile option on command handlers."""

    def test_subscription_profile_production(self, test_domain):
        """PRODUCTION subscription profile can be set."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert (
            OrderCommandHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )

    def test_subscription_profile_fast(self, test_domain):
        """FAST subscription profile can be set."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.FAST,
        )
        class FastCommandHandler(BaseCommandHandler):
            pass

        assert FastCommandHandler.meta_.subscription_profile == SubscriptionProfile.FAST

    def test_subscription_profile_batch(self, test_domain):
        """BATCH subscription profile can be set."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.BATCH,
        )
        class BatchCommandHandler(BaseCommandHandler):
            pass

        assert (
            BatchCommandHandler.meta_.subscription_profile == SubscriptionProfile.BATCH
        )

    def test_subscription_profile_debug(self, test_domain):
        """DEBUG subscription profile can be set."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.DEBUG,
        )
        class DebugCommandHandler(BaseCommandHandler):
            pass

        assert (
            DebugCommandHandler.meta_.subscription_profile == SubscriptionProfile.DEBUG
        )

    def test_subscription_profile_via_register(self, test_domain):
        """Subscription profile can be set via domain.register()."""

        class OrderCommandHandler(BaseCommandHandler):
            pass

        test_domain.register(
            OrderCommandHandler,
            part_of=Order,
            subscription_profile=SubscriptionProfile.FAST,
        )
        assert (
            OrderCommandHandler.meta_.subscription_profile == SubscriptionProfile.FAST
        )


class TestCommandHandlerSubscriptionConfigOption:
    """Tests for subscription_config dict option on command handlers."""

    def test_subscription_config_via_decorator(self, test_domain):
        """Subscription config dict can be set via decorator."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_config={"messages_per_tick": 50, "max_retries": 5},
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert OrderCommandHandler.meta_.subscription_config == {
            "messages_per_tick": 50,
            "max_retries": 5,
        }

    def test_subscription_config_via_register(self, test_domain):
        """Subscription config can be set via domain.register()."""

        class OrderCommandHandler(BaseCommandHandler):
            pass

        test_domain.register(
            OrderCommandHandler,
            part_of=Order,
            subscription_config={"retry_delay_seconds": 2},
        )
        assert OrderCommandHandler.meta_.subscription_config == {
            "retry_delay_seconds": 2
        }

    def test_subscription_config_with_various_options(self, test_domain):
        """subscription_config can contain various subscription options."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_config={
                "messages_per_tick": 100,
                "tick_interval": 0,
                "blocking_timeout_ms": 5000,
                "max_retries": 3,
                "retry_delay_seconds": 1,
                "enable_dlq": True,
            },
        )
        class ConfiguredHandler(BaseCommandHandler):
            pass

        config = ConfiguredHandler.meta_.subscription_config
        assert config["messages_per_tick"] == 100
        assert config["tick_interval"] == 0
        assert config["blocking_timeout_ms"] == 5000
        assert config["max_retries"] == 3
        assert config["retry_delay_seconds"] == 1
        assert config["enable_dlq"] is True


class TestCommandHandlerCombinedSubscriptionOptions:
    """Tests for combining multiple subscription options."""

    def test_all_subscription_options_together(self, test_domain):
        """All subscription options can be set together."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={"messages_per_tick": 100},
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        assert OrderCommandHandler.meta_.subscription_type == SubscriptionType.STREAM
        assert (
            OrderCommandHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )
        assert OrderCommandHandler.meta_.subscription_config == {
            "messages_per_tick": 100
        }

    def test_subscription_options_with_derived_stream_category(self, test_domain):
        """Command handler has subscription options and derived stream_category."""
        test_domain.register(Order)

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        # stream_category should be derived from Order aggregate
        assert (
            OrderCommandHandler.meta_.stream_category
            == f"{Order.meta_.stream_category}:command"
        )
        assert (
            OrderCommandHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )


class TestCommandHandlerSubscriptionInheritance:
    """Tests for subscription configuration inheritance behavior."""

    def test_subscription_options_not_inherited_by_subclass(self, test_domain):
        """Subscription options are not automatically inherited by subclasses."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class BaseOrderCommandHandler(BaseCommandHandler):
            pass

        @test_domain.command_handler(part_of=Order)
        class DerivedOrderCommandHandler(BaseCommandHandler):
            pass

        assert (
            BaseOrderCommandHandler.meta_.subscription_profile
            == SubscriptionProfile.PRODUCTION
        )
        assert DerivedOrderCommandHandler.meta_.subscription_profile is None


class TestCommandHandlerMissingSubscriptionOptions:
    """Tests for handling cases where subscription options are missing or partial."""

    def test_command_handler_without_subscription_options(self, test_domain):
        """Command handler without subscription options gets defaults."""

        @test_domain.command_handler(part_of=Order)
        class SimpleCommandHandler(BaseCommandHandler):
            pass

        assert SimpleCommandHandler.meta_.subscription_type is None
        assert SimpleCommandHandler.meta_.subscription_profile is None
        assert SimpleCommandHandler.meta_.subscription_config == {}

    def test_command_handler_with_partial_options(self, test_domain):
        """Command handler with some options leaves others as defaults."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.FAST,
            # subscription_type and subscription_config not specified
        )
        class PartialHandler(BaseCommandHandler):
            pass

        assert PartialHandler.meta_.subscription_type is None
        assert PartialHandler.meta_.subscription_profile == SubscriptionProfile.FAST
        assert PartialHandler.meta_.subscription_config == {}
