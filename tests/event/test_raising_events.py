from uuid import uuid4

import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class UserLoggedIn(BaseEvent):
    user_id: str = Field(json_schema_extra={"identifier": True})


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
    assert messages[0].metadata.headers.stream == f"test::authentication-{identifier}"
