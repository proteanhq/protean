from enum import Enum

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import HasOne, Identifier, String
from protean.utils.globals import current_domain


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Account(BaseEntity):
    password_hash = String(max_length=512)

    def change_password(self, password):
        self.password_hash = password
        self.raise_(PasswordChanged(account_id=self.id, user_id=self.user_id))


class PasswordChanged(BaseEvent):
    account_id = Identifier(required=True)
    user_id = Identifier(required=True)


class User(BaseAggregate):
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=UserStatus)

    account = HasOne(Account)

    def activate(self):
        self.raise_(UserActivated(user_id=self.id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.id, name=name))


class UserActivated(BaseEvent):
    user_id = Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True, max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Account, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(PasswordChanged, part_of=User)
    test_domain.init(traverse=False)


def test_that_aggregate_has_events_list():
    user = User(name="John Doe", email="john.doe@example.com")
    assert hasattr(user, "_events")
    assert user._events == []


def test_raising_events():
    user = User(name="John Doe", email="john.doe@example.com")
    user.activate()

    assert len(user._events) == 1
    assert isinstance(user._events[0], UserActivated)


def test_that_events_are_registered_in_the_right_order():
    user = User(name="John Doe", email="john.doe@example.com")
    user.change_name("Jane Doe")
    user.activate()

    assert len(user._events) == 2
    assert isinstance(user._events[0], UserRenamed)
    assert isinstance(user._events[1], UserActivated)


@pytest.mark.eventstore
def test_that_events_are_empty_after_uow():
    user = User(name="John Doe", email="john.doe@example.com")
    user.change_name("Jane Doe")
    user.activate()

    with UnitOfWork():
        user_repo = current_domain.repository_for(User)
        user_repo.add(user)

    assert len(user._events) == 0


@pytest.mark.eventstore
def test_events_can_be_raised_by_entities():
    user = User(
        name="John Doe",
        email="john.doe@example.com",
        account=Account(password_hash="password"),
    )

    user.account.change_password("new_password")

    assert len(user._events) == 1
    # Events are still stored at the aggregate level
    assert len(user.account._events) == 0
    assert isinstance(user._events[0], PasswordChanged)

    with UnitOfWork():
        user_repo = current_domain.repository_for(User)
        user_repo.add(user)

    assert len(user._events) == 0
    assert len(user.account._events) == 0
