from uuid import uuid4

import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent


class User(BaseAggregate):
    id: str = Field(json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))


class UserLoggedIn(BaseEvent):
    user_id: str | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_is_generated_with_unique_id():
    identifier = str(uuid4())
    user = User(id=identifier, email="foo@bar.com", name="Foo Bar")
    user.login()

    event = user._events[0]
    assert event._metadata.headers.id == f"test::user-{identifier}-0"
    assert event._metadata.domain.sequence_id == "0"
