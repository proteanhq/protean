from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.fields import DateTime, Identifier, String, Text
from protean.utils import utcnow_func


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class Activated(BaseEvent):
    id = Identifier(required=True)


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)


class User(BaseAggregate):
    email = String()
    name = String(max_length=50)

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

    @apply
    def on_registered(self, event: Registered):
        self.id = event.id
        self.email = event.email
        self.name = event.name

    @apply
    def on_activated(self, event: Activated):
        pass

    @apply
    def on_renamed(self, event: Renamed):
        self.name = event.name


class Created(BaseEvent):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()


class Published(BaseEvent):
    id = Identifier(required=True)
    published_time = DateTime(default=utcnow_func)


class Post(BaseAggregate):
    topic = String()
    content = Text()

    @classmethod
    def create(self, id, topic, content):
        post = Post(id=id, topic=topic, content=content)
        post.raise_(Created(id=id, topic=topic, content=content))

        return post

    def publish(self):
        self.raise_(Published(id=self.id))

    @apply
    def on_created(self, event: Created):
        self.id = event.id
        self.topic = event.topic
        self.content = event.content

    @apply
    def on_published(self, event: Published):
        pass


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
