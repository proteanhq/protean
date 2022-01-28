from enum import Enum

import pytest

from protean import BaseAggregate, BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.globals import current_domain


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class User(BaseAggregate):
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=UserStatus)

    def activate(self):
        self.raise_(UserActivated(user_id=self.id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.id, name=name))


class UserActivated(BaseEvent):
    user_id = Identifier(required=True)

    class Meta:
        aggregate_cls = User


class UserRenamed(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True, max_length=50)

    class Meta:
        aggregate_cls = User


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)


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
