from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils import fqn


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_payload():
    user_id = str(uuid4())
    user = User(id=user_id, email="<EMAIL>", name="<NAME>")

    user.login()
    event = user._events[0]

    assert event.to_dict() == {
        "_metadata": {
            "id": f"test::user-{user_id}-0",
            "type": "Test.UserLoggedIn.v1",
            "fqn": fqn(UserLoggedIn),
            "kind": "EVENT",
            "stream": f"test::user-{user_id}",
            "origin_stream": None,
            "timestamp": str(event._metadata.timestamp),
            "version": "v1",
            "sequence_id": "0",
            "payload_hash": event._metadata.payload_hash,
            "asynchronous": False,  # Test Domain event_processing is SYNC by default
        },
        "user_id": event.user_id,
    }

    assert event.payload == {
        "user_id": event.user_id,
    }
