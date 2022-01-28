from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)

    class Meta:
        stream_name = "authentication"


@pytest.mark.eventstore
def test_raising_event(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn)

    identifier = str(uuid4())
    test_domain.raise_(UserLoggedIn(user_id=identifier))

    messages = test_domain.event_store.store.read("authentication")

    assert len(messages) == 1
    assert messages[0].stream_name == f"authentication-{identifier}"
