from enum import Enum
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
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


class User(BaseAggregate):
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
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_expected_version_error(test_domain):
    identifier = str(uuid4())

    with UnitOfWork():
        repo = test_domain.repository_for(User)
        user = User.register(
            user_id=identifier, name="John Doe", email="john.doe@example.com"
        )
        repo.add(user)

    user_dup1 = repo.get(identifier)
    user_dup2 = repo.get(identifier)

    with UnitOfWork():
        user_dup1.activate()
        repo.add(user_dup1)

    with pytest.raises(ExpectedVersionError) as exc:
        with UnitOfWork():
            user_dup2.change_name("Mike")
            repo.add(user_dup2)

    assert (
        exc.value.args[0]
        == f"Wrong expected version: 0 (Stream: test::user-{identifier}, Stream Version: 1)"
    )
