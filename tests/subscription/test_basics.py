from __future__ import annotations

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import handle


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()

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


def test_subscriber_class_name_is_set_on_subscription_init(test_domain):
    engine = Engine(test_domain, test_mode=True)
    assert (
        engine._subscriptions[fqn(UserEventHandler)].subscriber_class_name
        == "UserEventHandler"
    )
    assert (
        engine._broker_subscriptions[fqn(UserSubscriber)].subscriber_class_name
        == "UserSubscriber"
    )
