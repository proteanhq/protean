from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.server import Engine
from protean.utils.eventing import Message
from protean.utils.mixins import handle

counter = 0


def count_up():
    global counter
    counter += 1


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class Post(BaseAggregate):
    topic: str | None = None
    content: str | None = None


class Created(BaseEvent):
    id: str | None = None
    topic: str | None = None
    content: str | None = None


class SystemMetrics(BaseEventHandler):
    @handle("$any")
    def increment(self, event: BaseEventHandler) -> None:
        count_up()


@pytest.mark.asyncio
@pytest.mark.eventstore
async def test_that_any_message_can_be_handled_with_any_handler(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Post, is_event_sourced=True)
    test_domain.register(Created, part_of=Post)
    test_domain.register(SystemMetrics, stream_category="$all")
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
    message1 = Message.from_domain_object(user._events[-1])

    post_identifier = str(uuid4())
    post = Post(
        id=post_identifier,
        topic="Foo",
        content="Bar",
    )
    post.raise_(Created(id=post_identifier, topic="Foo", content="Bar"))

    test_domain.event_store.store.append(post._events[-1])
    message2 = Message.from_domain_object(post._events[-1])

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(SystemMetrics, message1)
    await engine.handle_message(SystemMetrics, message2)

    global counter
    assert counter == 2
