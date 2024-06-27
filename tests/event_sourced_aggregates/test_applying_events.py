from enum import Enum
from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate, apply
from protean.fields import Identifier, String


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class UserRegistered(BaseEvent):
    user_id = Identifier(required=True)
    name = String(max_length=50, required=True)
    email = String(required=True)


class UserActivated(BaseEvent):
    user_id = Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True, max_length=50)


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=UserStatus)

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self):
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply
    def registered(self, _: UserRegistered):
        self.status = UserStatus.INACTIVE.value

    @apply
    def activated(self, _: UserActivated):
        self.status = UserStatus.ACTIVE.value

    @apply
    def renamed(self, event: UserRenamed):
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_applying_events():
    identifier = str(uuid4())

    registered = UserRegistered(
        user_id=identifier, name="John Doe", email="john.doe@example.com"
    )
    activated = UserActivated(user_id=identifier)
    renamed = UserRenamed(user_id=identifier, name="Jane Doe")

    user = User.register(**registered.payload)

    user._apply(registered)
    assert user.status == UserStatus.INACTIVE.value

    user._apply(activated)
    assert user.status == UserStatus.ACTIVE.value

    user._apply(renamed)
    assert user.name == "Jane Doe"
