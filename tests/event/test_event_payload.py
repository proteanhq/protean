from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils import fqn
from protean.utils.eventing import MessageEnvelope


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

    # Compute expected checksum
    expected_checksum = MessageEnvelope.compute_checksum(event.payload)

    assert event.to_dict() == {
        "_metadata": {
            "envelope": {
                "specversion": "1.0",
                "checksum": expected_checksum,
            },
            "headers": {
                "id": f"test::user-{user_id}-0",
                "type": "Test.UserLoggedIn.v1",
                "stream": f"test::user-{user_id}",
                "time": str(event._metadata.headers.time),
                "traceparent": None,
            },
            "domain": {
                "fqn": fqn(UserLoggedIn),
                "kind": "EVENT",
                "origin_stream": None,
                "version": "v1",
                "sequence_id": "0",
                "asynchronous": False,  # Test Domain event_processing is SYNC by default
                "expected_version": None,
            },
        },
        "user_id": event.user_id,
    }

    assert event.payload == {
        "user_id": event.user_id,
    }
