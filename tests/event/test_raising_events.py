from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.mark.eventstore
def test_raising_event(test_domain):
    test_domain.register(User, is_event_sourced=True, stream_category="authentication")
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    user = User(id=identifier, email="test@example.com", name="Test User")
    user.raise_(UserLoggedIn(user_id=identifier))

    test_domain.repository_for(User).add(user)

    messages = test_domain.event_store.store.read("test::authentication")

    assert len(messages) == 1
    assert messages[0].stream_name == f"test::authentication-{identifier}"
