from datetime import datetime
from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_metadata(test_domain):
    user_id = str(uuid4())
    user = User(id=user_id, email="<EMAIL>", name="<NAME>")

    user.login()

    assert len(user._events) == 1

    event = user._events[0]
    assert event._metadata is not None

    assert event._metadata.kind == "EVENT"
    assert isinstance(event._metadata.timestamp, datetime)
    # assert event._metadata.id == f"test.user.v1.{user.user_id}.1"

    assert event.to_dict() == {
        "_metadata": {
            "kind": "EVENT",
            "timestamp": str(event._metadata.timestamp),
        },
        "user_id": event.user_id,
    }
