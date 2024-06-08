from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import DateTime, Identifier, String, Text
from protean.utils import utcnow_func


class User(BaseEventSourcedAggregate):
    email = String()
    name = String(max_length=50)


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class Activated(BaseEvent):
    id = Identifier(required=True)


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)


class Post(BaseEventSourcedAggregate):
    topic = String()
    content = Text()


class Created(BaseEvent):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()


class Published(BaseEvent):
    id = Identifier(required=True)
    published_time = DateTime(default=utcnow_func)


@pytest.mark.eventstore
def test_reading_messages_from_all_streams(test_domain):
    user_identifier = str(uuid4())
    event1 = Registered(id=user_identifier, email="john.doe@example.com")
    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    event2 = Activated(id=user_identifier)
    test_domain.event_store.store.append_aggregate_event(user, event2)

    event3 = Renamed(id=user_identifier, name="Jane Doe")
    test_domain.event_store.store.append_aggregate_event(user, event3)

    post_identifier = str(uuid4())
    event4 = Created(id=post_identifier, topic="Foo", content="Bar")
    post = Post(**event4.to_dict())
    test_domain.event_store.store.append_aggregate_event(post, event4)

    event5 = Published(id=post_identifier)
    test_domain.event_store.store.append_aggregate_event(post, event5)

    messages = test_domain.event_store.store.read("$all")
    assert len(messages) == 5
