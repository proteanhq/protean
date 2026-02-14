from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.utils import utcnow_func


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None

    @classmethod
    def register(cls, id, email, name):
        user = User(id=id, email=email, name=name)
        user.raise_(Registered(id=id, email=email, name=name))

        return user

    def activate(self):
        self.raise_(Activated(id=self.id))

    def rename(self, name):
        self.name = name
        self.raise_(Renamed(id=self.id, name=name))


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None


class Activated(BaseEvent):
    id: str


class Renamed(BaseEvent):
    id: str
    name: str


class Post(BaseAggregate):
    topic: str | None = None
    content: str | None = None

    @classmethod
    def create(self, id, topic, content):
        post = Post(id=id, topic=topic, content=content)
        post.raise_(Created(id=id, topic=topic, content=content))

        return post

    def publish(self):
        self.raise_(Published(id=self.id))


class Created(BaseEvent):
    id: str | None = None
    topic: str | None = None
    content: str | None = None


class Published(BaseEvent):
    id: str
    published_time: datetime = Field(default_factory=utcnow_func)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)

    test_domain.register(Post, is_event_sourced=True)
    test_domain.register(Created, part_of=Post)
    test_domain.register(Published, part_of=Post)

    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_reading_messages_from_all_streams(test_domain):
    user_identifier = str(uuid4())
    user = User.register(
        id=user_identifier, email="john.doe@example.com", name="John Doe"
    )
    test_domain.event_store.store.append(user._events[0])

    user.activate()
    test_domain.event_store.store.append(user._events[1])

    user.rename(name="Johnny Doe")
    test_domain.event_store.store.append(user._events[2])

    post_identifier = str(uuid4())
    post = Post.create(id=post_identifier, topic="Foo", content="Bar")
    test_domain.event_store.store.append(post._events[0])

    post.publish()
    test_domain.event_store.store.append(post._events[1])

    messages = test_domain.event_store.store.read("$all")
    assert len(messages) == 5
