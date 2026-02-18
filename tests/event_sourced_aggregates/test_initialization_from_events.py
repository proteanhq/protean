from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.fields import Identifier, String


class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    name: String(max_length=50, required=True)
    email: String(required=True)


class UserActivated(BaseEvent):
    user_id: Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=["ACTIVE", "INACTIVE", "ARCHIVED"], default="INACTIVE")

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    @apply
    def registered(self, event: UserRegistered):
        self.user_id = event.user_id
        self.name = event.name
        self.email = event.email
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
