from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.mixins import Message

counter = 0


def count_up():
    global counter
    counter += 1


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()

    class Meta:
        aggregate_cls = User


class UserEventHandler(BaseEventHandler):
    @handle("$any")
    def increment(self, event: BaseEventHandler) -> None:
        count_up()


@pytest.mark.asyncio
async def test_that_an_event_handler_can_be_associated_with_an_all_stream(test_domain):
    test_domain.register(User)
    test_domain.register(Registered)
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
    message = Message.to_aggregate_event_message(user, event)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(UserEventHandler, message)

    global counter
    assert counter == 1
