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
from protean.core.process_manager import BaseProcessManager
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


def _register_user_event_handler(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)


def _subscription_for(engine, handler_cls):
    return engine._subscriptions[f"{handler_cls.__module__}.{handler_cls.__qualname__}"]


class TestEngineSubscriptionFactoryIntegration:
    """Tests for Engine integration with SubscriptionFactory."""

    def test_engine_exposes_a_subscription_factory_bound_to_it(self, test_domain):
        _register_user_event_handler(test_domain)

        engine = Engine(test_domain, test_mode=True)

        assert isinstance(engine._subscription_factory, SubscriptionFactory)
        assert engine.subscription_factory is engine._subscription_factory
        assert engine.subscription_factory.engine is engine


class TestEngineSubscriptionCreation:
    """Tests for Engine automatic subscription creation."""

    def test_event_handler_subscription_reads_the_part_of_stream(self, test_domain):
        """The engine subscribes an event handler to its part_of aggregate's
        stream and wires the subscription back to the engine and handler."""
        test_domain.config["server"]["default_subscription_type"] = "stream"
        _register_user_event_handler(test_domain)

        engine = Engine(test_domain, test_mode=True)

        subscription = _subscription_for(engine, UserEventHandler)
        assert subscription.engine is engine
        assert subscription.handler == UserEventHandler
        assert subscription.stream_category == User.meta_.stream_category

    def test_creates_subscription_for_command_handler(self, test_domain):
        """Engine should create a CommandDispatcher subscription for registered command handlers."""
        test_domain.register(User, event_sourced=True)
        test_domain.register(RegisterUser, part_of=User)
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        # CommandDispatcher groups by stream category
        stream_category = User.meta_.stream_category + ":command"
        subscription_key = f"commands:{stream_category}"
        assert subscription_key in engine._subscriptions
        assert (
            engine._subscriptions[subscription_key].stream_category == stream_category
        )

    def test_creates_multiple_subscriptions(self, test_domain):
        """Engine should create subscriptions for multiple handlers."""
        test_domain.register(User, event_sourced=True)
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

    @pytest.mark.parametrize(
        "default_type, expected_cls",
        [("stream", StreamSubscription), ("event_store", EventStoreSubscription)],
    )
    def test_uses_server_default_subscription_type(
        self, test_domain, default_type, expected_cls
    ):
        test_domain.config["server"]["default_subscription_type"] = default_type
        _register_user_event_handler(test_domain)

        engine = Engine(test_domain, test_mode=True)

        assert isinstance(_subscription_for(engine, UserEventHandler), expected_cls)

    def test_handler_subscription_type_and_stream_override_server_default(
        self, test_domain
    ):
        """Handler's subscription_type and stream_category override the defaults."""
        # Server default is stream
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        # Register handler with EVENT_STORE subscription type
        test_domain.register(
            ProjectionHandler,
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        subscription = _subscription_for(engine, ProjectionHandler)
        # Should be EventStoreSubscription despite server default being stream
        assert isinstance(subscription, EventStoreSubscription)
        assert subscription.stream_category == "$all"


class TestEngineSubscriptionProfile:
    """Tests for subscription profile support."""

    def test_uses_handler_subscription_profile(self, test_domain):
        """Engine should use handler's subscription_profile."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        test_domain.register(User, event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            ProductionEventHandler,
            part_of=User,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        subscription = _subscription_for(engine, ProductionEventHandler)

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
        _register_user_event_handler(test_domain)

        engine = Engine(test_domain, test_mode=True)

        # BATCH profile settings
        assert _subscription_for(engine, UserEventHandler).messages_per_tick == 500


class TestEngineInferStreamCategory:
    """Tests for _infer_stream_category method."""

    def test_infer_stream_category_from_explicit(self, test_domain):
        """Should return explicit stream_category from handler Meta."""
        test_domain.register(User, event_sourced=True)
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

    def test_infer_stream_category_raises_when_cannot_infer(self, test_domain):
        """Should raise ValueError when stream category cannot be inferred."""

        # Create a handler without part_of or stream_category
        class OrphanHandler(BaseEventHandler):
            @handle(UserRegistered)
            def handle_event(self, event: UserRegistered) -> None:
                pass

        _register_user_event_handler(test_domain)

        engine = Engine(test_domain, test_mode=True)

        # OrphanHandler has meta_ but no stream_category or part_of
        with pytest.raises(ValueError, match="Cannot infer stream category"):
            engine._infer_stream_category(OrphanHandler)

    def test_infer_stream_category_raises_when_no_meta(self, test_domain):
        """Should raise ValueError when handler has no meta_ attribute."""
        _register_user_event_handler(test_domain)

        engine = Engine(test_domain, test_mode=True)

        class NoMetaHandler:
            pass

        with pytest.raises(ValueError, match="has no meta_ attribute"):
            engine._infer_stream_category(NoMetaHandler)

    def test_infer_stream_category_from_part_of_aggregate_meta(self, test_domain):
        """Should infer stream_category from part_of aggregate's meta_ when handler has no explicit stream_category."""

        class LocalUserEventHandler(BaseEventHandler):
            @handle(UserRegistered)
            def handle_event(self, event: UserRegistered) -> None:
                pass

        _register_user_event_handler(test_domain)
        test_domain.register(LocalUserEventHandler, part_of=User)
        engine = Engine(test_domain, test_mode=True)

        # Registration copies the aggregate's stream category onto the
        # handler; clear it so only part_of is left to infer from.
        LocalUserEventHandler.meta_.stream_category = None

        result = engine._infer_stream_category(LocalUserEventHandler)
        assert result == User.meta_.stream_category


class TestEngineConfigPriority:
    """Tests for configuration priority hierarchy."""

    def test_handler_config_overrides_server_config(self, test_domain):
        """Handler subscription_config should override server config."""
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.config["server"]["messages_per_tick"] = 200

        test_domain.register(User, event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            CustomConfigHandler,
            part_of=User,
            subscription_config={"messages_per_tick": 75, "max_retries": 10},
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        subscription = _subscription_for(engine, CustomConfigHandler)

        # Handler config (75) should override server config (200)
        assert subscription.messages_per_tick == 75
        assert subscription.max_retries == 10

    def test_handler_profile_overrides_server_profile(self, test_domain):
        """Handler subscription_profile should override server default_subscription_profile."""
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.config["server"]["default_subscription_profile"] = "batch"  # 500

        test_domain.register(User, event_sourced=True)
        test_domain.register(UserRegistered, part_of=User)
        test_domain.register(
            ProductionEventHandler,
            part_of=User,
            subscription_profile=SubscriptionProfile.FAST,  # 10
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        # Handler FAST profile (10) should override server BATCH profile (500)
        assert _subscription_for(engine, ProductionEventHandler).messages_per_tick == 10


# -----------------------------------------------------------------------
# Process Manager subscription registration
# -----------------------------------------------------------------------


class Order(BaseAggregate):
    customer_id: Identifier()


class OrderPlaced(BaseEvent):
    order_id: Identifier()


class Payment(BaseAggregate):
    order_id: Identifier()


class PaymentConfirmed(BaseEvent):
    order_id: Identifier()


class OrderFulfillmentPM(BaseProcessManager):
    order_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        self.status = "paid"


class TestEngineProcessManagerSubscriptions:
    """Tests for Engine subscription creation for Process Managers."""

    def test_creates_one_subscription_per_pm_stream_category(self, test_domain):
        """Engine should create a subscription for each PM stream category,
        each reading its own stream with the PM class as handler."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(Payment)
        test_domain.register(PaymentConfirmed, part_of=Payment)
        test_domain.register(
            OrderFulfillmentPM,
            stream_categories=["test::order", "test::payment"],
        )
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        pm_name = f"{OrderFulfillmentPM.__module__}.{OrderFulfillmentPM.__qualname__}"
        for stream_category in ("test::order", "test::payment"):
            subscription = engine._subscriptions[f"{pm_name}-{stream_category}"]
            assert subscription.handler == OrderFulfillmentPM
            assert subscription.stream_category == stream_category
