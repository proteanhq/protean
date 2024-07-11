from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields.basic import Identifier
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.mark.eventstore
def test_appending_raw_events(test_domain):
    test_domain.register(User, stream_name="authentication")
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    user = User(user_id=identifier)
    user.raise_(UserLoggedIn(user_id=identifier))
    event = user._events[0]  # Remember event for later comparison
    test_domain.repository_for(User).add(user)

    messages = test_domain.event_store.store.read("authentication")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)

    assert message.stream_name == f"authentication-{identifier}"
    assert message.metadata.kind == "EVENT"
    assert message.data == event.payload
    assert message.metadata == event._metadata
