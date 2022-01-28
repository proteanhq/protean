from __future__ import annotations

from uuid import uuid4

import mock
import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import Identifier, String
from protean.globals import current_domain
from protean.server import Engine
from protean.server.subscription import Subscription
from protean.utils import TypeMatcher, fully_qualified_name
from protean.utils.mixins import Message

counter = 0


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


def count_up():
    global counter
    counter += 1


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_notification(self, event: Registered) -> None:
        count_up()


@pytest.mark.asyncio
@pytest.mark.eventstore
@mock.patch("protean.server.engine.Engine.handle_message")
async def test_that_subscription_invokes_engine_handler_on_message(
    mock_handle_message, test_domain
):
    test_domain.register(User)
    test_domain.register(UserEventHandler, aggregate_cls=User)

    identifier = str(uuid4())
    user = User(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    event = Registered(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    current_domain.event_store.store.append_aggregate_event(user, event)

    engine = Engine(test_domain, test_mode=True)
    subscription = Subscription(
        engine, fully_qualified_name(UserEventHandler), "user", UserEventHandler
    )
    await subscription.poll()

    mock_handle_message.assert_called_once_with(UserEventHandler, TypeMatcher(Message))
