from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.mixins import Message, handle

counter = 0


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
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
async def test_handler_invocation(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    user = User(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    user.raise_(
        Registered(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )
    message = Message.to_message(user._events[-1])

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(UserEventHandler, message)

    global counter
    assert counter == 1
