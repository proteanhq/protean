from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.fields.basic import Identifier
from protean.utils.eventing import Message


class User(BaseAggregate):
    user_id = Identifier(identifier=True)


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.mark.eventstore
def test_appending_raw_events(test_domain):
    test_domain.register(User, is_event_sourced=True, stream_category="authentication")
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    user = User(user_id=identifier)
    user.raise_(UserLoggedIn(user_id=identifier))
    event = user._events[0]  # Remember event for later comparison
    test_domain.repository_for(User).add(user)

    messages = test_domain.event_store.store.read("test::authentication")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)

    assert message.metadata.headers.stream == f"test::authentication-{identifier}"
    assert message.metadata.domain.kind == "EVENT"
    assert message.data == event.payload
    # Compare metadata fields (except envelope which now has checksum in message)
    assert message.metadata.domain.fqn == event._metadata.domain.fqn
    assert message.metadata.domain.kind == event._metadata.domain.kind
    assert message.metadata.headers.stream == event._metadata.headers.stream
    assert message.metadata.headers == event._metadata.headers
