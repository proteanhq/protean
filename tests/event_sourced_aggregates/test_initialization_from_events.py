from uuid import uuid4

import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent


class UserRegistered(BaseEvent):
    user_id: str
    name: str
    email: str


class UserActivated(BaseEvent):
    user_id: str


class UserRenamed(BaseEvent):
    user_id: str
    name: str


class User(BaseAggregate):
    user_id: str = Field(json_schema_extra={"identifier": True})
    name: str
    email: str
    status: str = "INACTIVE"

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    @apply
    def registered(self, event: UserRegistered):
        self.status = "INACTIVE"

    def activate(self):
        self.status = "ACTIVE"
        self.raise_(UserActivated(user_id=self.user_id))

    @apply
    def activated(self, event: UserActivated):
        self.status = "ACTIVE"

    def change_name(self, name):
        self.name = name
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply
    def renamed(self, event: UserRenamed):
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.init(traverse=False)


def test_initialization_from_events(test_domain):
    user = User.register(user_id=str(uuid4()), name="<NAME>", email="<EMAIL>")
    user.activate()
    user.change_name("<NAME>")

    assert len(user._events) == 3

    # Simulate reloading user from events
    user_from_events = User.from_events(user._events)

    assert user_from_events == user
