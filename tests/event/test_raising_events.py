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


@pytest.mark.eventstore
def test_raising_event(test_domain):
    test_domain.register(User, stream_name="authentication")
    test_domain.register(UserLoggedIn, part_of=User)

    identifier = str(uuid4())
    user = User(id=identifier, email="test@example.com", name="Test User")
    user.raise_(UserLoggedIn(user_id=identifier))

    test_domain.repository_for(User).add(user)

    messages = test_domain.event_store.store.read("authentication")

    assert len(messages) == 1
    assert messages[0].stream_name == f"authentication-{identifier}"
