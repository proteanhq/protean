from __future__ import annotations

import asyncio

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()


class Sent(BaseEvent):
    email = String()
    sent_on = DateTime()


class User(BaseEventSourcedAggregate):
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


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, event: Sent) -> None:
        pass


@pytest.fixture(autouse=True)
def setup_event_loop():
    """Ensure an Event Loop Exists in Tests.

    Otherwise tests are attempting to access the asyncio event loop from a non-async context
    where no event loop is running or set as the current event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


def test_event_subscriptions(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    engine = Engine(test_domain, test_mode=True)

    assert len(engine._subscriptions) == 1
    assert fqn(UserEventHandler) in engine._subscriptions
    assert engine._subscriptions[fqn(UserEventHandler)].stream_category == "user"


def test_origin_stream_category_in_subscription(test_domain):
    test_domain.register(User)
    test_domain.register(Sent, part_of=User)
    test_domain.register(EmailEventHandler, part_of=User, source_stream="email")

    engine = Engine(test_domain, test_mode=True)

    assert len(engine._subscriptions) == 1
    assert engine._subscriptions[fqn(EmailEventHandler)].stream_category == "user"
    assert engine._subscriptions[fqn(EmailEventHandler)].origin_stream_name == "email"


def test_that_stream_name_overrides_the_derived_stream_name_from_owning_aggregate(
    test_domain,
):
    test_domain.register(
        EmailEventHandler,
        part_of=User,
        stream_category="identity",
        source_stream="email",
    )

    engine = Engine(test_domain, test_mode=True)

    assert len(engine._subscriptions) == 1
    assert engine._subscriptions[fqn(EmailEventHandler)].stream_category == "identity"
    assert engine._subscriptions[fqn(EmailEventHandler)].origin_stream_name == "email"
