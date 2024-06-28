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


def test_event_is_generated_with_unique_id():
    identifier = str(uuid4())
    user = User(id=identifier, email="foo@bar.com", name="Foo Bar")
    user.login()

    event = user._events[0]
    assert event._metadata.id == f"Test.User.v1.{identifier}.0"
    assert event._metadata.sequence_id == "0"
