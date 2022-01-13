from __future__ import annotations

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fully_qualified_name


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


def dummy(*args):
    pass


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, event: Registered) -> None:
        dummy(event)

    @handle(Activated)
    def provision_user(self, event: Activated) -> None:
        dummy(event)

    @handle(Activated)
    def send_welcome_email(self, event: Activated) -> None:
        dummy(event)


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(UserEventHandler, aggregate_cls=User)


@pytest.fixture
def engine(test_domain):
    return Engine(test_domain, test_mode=True)


def test_event_subscriptions(engine):
    assert len(engine._subscriptions) == 1
    assert fully_qualified_name(UserEventHandler) in engine._subscriptions
    assert (
        engine._subscriptions[fully_qualified_name(UserEventHandler)].stream_name
        == "user"
    )
