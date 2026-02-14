import os
import re
import socket
from unittest.mock import patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber

from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import handle


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None

    @classmethod
    def register(cls, id, email, name, password_hash):
        user = User(id=id, email=email, name=name, password_hash=password_hash)
        user.raise_(
            Registered(id=id, email=email, name=name, password_hash=password_hash)
        )

        return user


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        pass


class UserSubscriber(BaseSubscriber):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserSubscriber, stream="user")
    test_domain.init(traverse=False)


class TestSubscriptionId:
    """Test subscription_id generation for Subscription class"""

    def test_subscription_id_is_generated(self, test_domain):
        """Test that subscription_id is created during initialization"""
        engine = Engine(test_domain, test_mode=True)

        subscription = engine._subscriptions[fqn(UserEventHandler)]

        assert hasattr(subscription, "subscription_id")
        assert subscription.subscription_id is not None
        assert isinstance(subscription.subscription_id, str)

    def test_subscription_id_format(self, test_domain):
        """Test that subscription_id follows the expected format: subscriber_class_name-hostname-pid-randomhex"""
        engine = Engine(test_domain, test_mode=True)

        subscription = engine._subscriptions[fqn(UserEventHandler)]

        # Should match pattern: subscriber_class_name-hostname-pid-6hexdigits
        pattern = r"^.+-.+-\d+-[0-9a-f]{6}$"
        assert re.match(pattern, subscription.subscription_id)

    def test_subscription_id_contains_hostname(self, test_domain):
        """Test that subscription_id contains the hostname"""
        engine = Engine(test_domain, test_mode=True)

        subscription = engine._subscriptions[fqn(UserEventHandler)]

        expected_hostname = socket.gethostname()
        assert expected_hostname in subscription.subscription_id

    def test_subscription_id_contains_pid(self, test_domain):
        """Test that subscription_id contains the process ID"""
        engine = Engine(test_domain, test_mode=True)

        subscription = engine._subscriptions[fqn(UserEventHandler)]

        expected_pid = str(os.getpid())
        assert expected_pid in subscription.subscription_id

    def test_subscription_id_contains_subscriber_class_name(self, test_domain):
        """Test that subscription_id contains the subscriber class name"""
        engine = Engine(test_domain, test_mode=True)

        subscription = engine._subscriptions[fqn(UserEventHandler)]

        assert subscription.subscription_id.startswith("UserEventHandler")

    def test_subscription_id_uniqueness(self, test_domain):
        """Test that multiple subscription instances have unique IDs"""
        engines = []
        for i in range(5):  # Reduced from 10 to avoid overhead
            engine = Engine(test_domain, test_mode=True)
            engines.append(engine)

        # All subscription IDs should be unique
        subscription_ids = [
            engine._subscriptions[fqn(UserEventHandler)].subscription_id
            for engine in engines
        ]
        assert len(subscription_ids) == len(set(subscription_ids))

    def test_subscription_id_with_mocked_components(self, test_domain):
        """Test subscription_id generation with mocked hostname, pid, and random hex"""
        with (
            patch("socket.gethostname", return_value="test-host"),
            patch("os.getpid", return_value=12345),
            patch("secrets.token_hex", return_value="abcdef"),
        ):
            engine = Engine(test_domain, test_mode=True)
            subscription = engine._subscriptions[fqn(UserEventHandler)]

            assert (
                subscription.subscription_id
                == "UserEventHandler-test-host-12345-abcdef"
            )

    def test_subscription_id_with_subscriber(self, test_domain):
        """Test that subscription_id contains the subscriber class name"""
        engine = Engine(test_domain, test_mode=True)
        subscription = engine._broker_subscriptions[fqn(UserSubscriber)]

        assert subscription.subscription_id.startswith("UserSubscriber")


class TestSubscriptionIdCrossEngine:
    """Test subscription_id generation across different engines"""

    def test_different_engines_have_unique_ids(self, test_domain):
        """Test that different Engine instances have unique subscription IDs"""
        engine1 = Engine(test_domain, test_mode=True)
        engine2 = Engine(test_domain, test_mode=True)

        subscription1 = engine1._subscriptions[fqn(UserEventHandler)]
        subscription2 = engine2._subscriptions[fqn(UserEventHandler)]

        # IDs should be different even for similar configurations
        assert subscription1.subscription_id != subscription2.subscription_id

    def test_subscription_id_components_consistency(self, test_domain):
        """Test that subscriptions use consistent format for subscription_id"""
        engine = Engine(test_domain, test_mode=True)

        subscription = engine._subscriptions[fqn(UserEventHandler)]

        # Should follow the expected pattern
        pattern = r"^.+-.+-\d+-[0-9a-f]{6}$"
        assert re.match(pattern, subscription.subscription_id)

        # Should contain hostname and PID
        hostname = socket.gethostname()
        pid = str(os.getpid())

        assert hostname in subscription.subscription_id
        assert pid in subscription.subscription_id

        # Should contain the handler name
        assert subscription.subscription_id.startswith("UserEventHandler")
