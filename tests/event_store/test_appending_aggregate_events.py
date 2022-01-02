from __future__ import annotations

from uuid import uuid4

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()


def test_appending_messages_to_aggregate(test_domain):
    identifier = str(uuid4())
    event = Registered(id=identifier, email="john.doe@example.com")
    user = User(id=identifier, email="john.doe@example.com")
    test_domain.event_store.store.append_aggregate_event(user, event)

    messages = test_domain.event_store.store._read("user")

    assert len(messages) == 1
