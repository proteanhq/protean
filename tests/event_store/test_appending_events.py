from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent
from protean.fields.basic import Identifier
from protean.utils.mixins import Message


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)

    class Meta:
        stream_name = "authentication"


@pytest.mark.eventstore
def test_appending_raw_events(test_domain):
    identifier = str(uuid4())
    event = UserLoggedIn(user_id=identifier)
    test_domain.event_store.store.append_event(event)

    messages = test_domain.event_store.store.read("authentication")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)

    assert message.stream_name == f"authentication-{identifier}"
    assert message.metadata.kind == "EVENT"
    assert message.data == event.to_dict()
