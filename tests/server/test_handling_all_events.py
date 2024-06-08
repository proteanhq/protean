from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import Identifier, String, Text
from protean.server import Engine
from protean.utils.mixins import Message

counter = 0


def count_up():
    global counter
    counter += 1


class User(BaseEventSourcedAggregate):
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Post(BaseEventSourcedAggregate):
    topic = String()
    content = Text()


class Created(BaseEvent):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()


class SystemMetrics(BaseEventHandler):
    @handle("$any")
    def increment(self, event: BaseEventHandler) -> None:
        count_up()

    class Meta:
        stream_name = "$all"


@pytest.mark.asyncio
@pytest.mark.eventstore
async def test_that_any_message_can_be_handled_with_any_handler(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Post)
    test_domain.register(Created, part_of=Post)
    test_domain.register(SystemMetrics, stream_name="$all")

    identifier = str(uuid4())
    registered = Registered(
        id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    user = User(**registered.to_dict())
    message1 = Message.to_aggregate_event_message(user, registered)

    post_identifier = str(uuid4())
    created = Created(id=post_identifier, topic="Foo", content="Bar")
    post = Post(**created.to_dict())
    test_domain.event_store.store.append_aggregate_event(post, created)
    message2 = Message.to_aggregate_event_message(post, created)

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(SystemMetrics, message1)
    await engine.handle_message(SystemMetrics, message2)

    global counter
    assert counter == 2
