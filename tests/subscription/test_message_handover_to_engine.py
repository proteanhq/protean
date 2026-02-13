from __future__ import annotations

from uuid import uuid4

import mock
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.utils import Processing, TypeMatcher
from protean.utils.eventing import Message
from protean.utils.mixins import handle

counter = 0


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
    test_domain.config["event_processing"] = Processing.ASYNC.value

    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    user = User.register(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    test_domain.repository_for(User).add(user)

    engine = Engine(test_domain, test_mode=True)
    subscription = EventStoreSubscription(engine, "test::user", UserEventHandler)
    await subscription.tick()

    mock_handle_message.assert_called_once_with(UserEventHandler, TypeMatcher(Message))
