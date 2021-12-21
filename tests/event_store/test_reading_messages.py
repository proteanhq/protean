from __future__ import annotations

from uuid import uuid4

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.mixins import Message


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()


def test_reading_messages(test_domain):
    identifier = str(uuid4())
    event = Registered(id=identifier, email="john.doe@example.com")
    user = User(id=identifier, email="john.doe@example.com")
    test_domain.event_store.store.append_event(user, event)

    messages = test_domain.event_store.store.read("user")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)
    assert message.stream_name == f"user-{identifier}"
    assert message.metadata.kind == "EVENT"
    assert message.data == event.to_dict()
