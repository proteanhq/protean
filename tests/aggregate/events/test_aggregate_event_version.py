from enum import Enum

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasOne, Identifier, String


class UserStatus(Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Account(BaseEntity):
    password_hash: String(max_length=512)

    def change_password(self, password):
        self.password_hash = password
        self.raise_(PasswordChanged(account_id=self.id, user_id=self.user_id))


class PasswordChanged(BaseEvent):
    account_id: Identifier(required=True)
    user_id: Identifier(required=True)


class User(BaseAggregate):
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=UserStatus, default=UserStatus.INACTIVE.value)

    account = HasOne(Account)

    @classmethod
    def register(cls, name, email):
        user = cls(name=name, email=email)
        user.raise_(UserRegistered(user_id=user.id, name=name, email=email))

        return user

    def activate(self):
        self.status = UserStatus.ACTIVE.value
        self.raise_(UserActivated(user_id=self.id))

    def change_email(self, email):
        # This method generates no events
        self.email = email

    def change_name(self, name):
        self.name = name
        self.raise_(UserRenamed(user_id=self.id, name=name))


class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    name: String(max_length=50, required=True)
    email: String(required=True)


class UserActivated(BaseEvent):
    user_id: Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Account, part_of=User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(PasswordChanged, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def user():
    return User.register(name="John Doe", email="john.doe@gmail.com")


def test_aggregate_tracks_event_version(user):
    assert user._version == -1

    # The aggregate's event position would have been incremented
    assert user._event_position == 0

    # Check for expected version inside the event
    assert user._events[0]._expected_version == -1


def test_aggregate_tracks_event_version_after_first_update(user, test_domain):
    assert user._events[0]._expected_version == -1

    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)

    assert refreshed_user._version == 0
    assert refreshed_user._event_position == 0


def test_aggregate_tracks_event_version_after_multiple_updates(user, test_domain):
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.activate()

    assert refreshed_user._events[0]._expected_version == 0

    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    assert refreshed_user._version == 1
    assert refreshed_user._event_position == 1


def test_aggregate_manages_event_version_with_an_update_and_no_events(test_domain):
    # We initialize user directly here to avoid raising events
    user = User(name="John Doe", email="john.doe@gmail.com")

    assert len(user._events) == 0

    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    assert refreshed_user._version == 0
    assert refreshed_user._event_position == -1


def test_aggregate_manages_event_version_with_multiple_updates_and_no_events(
    test_domain,
):
    user = User(name="John Doe", email="john.doe@gmail.com")
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_email("jane.doe@gmail.com")

    assert len(user._events) == 0

    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    assert refreshed_user._version == 1
    assert refreshed_user._event_position == -1


def test_aggregate_tracks_event_version_after_an_update_with_multiple_events(
    user, test_domain
):
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_name("Jane Doe")
    refreshed_user.activate()

    assert refreshed_user._events[0]._expected_version == 0
    assert refreshed_user._events[1]._expected_version == 1

    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    assert refreshed_user._version == 1
    assert refreshed_user._event_position == 2


@pytest.mark.xfail
def test_aggregate_tracks_event_version_after_multiple_updates_with_multiple_events(
    user, test_domain
):
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_name("Jane Doe")
    refreshed_user.activate()

    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)

    assert refreshed_user._version == 1
    assert refreshed_user._event_position == 2

    refreshed_user.account = Account(password_hash="hashed_password")

    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)

    assert refreshed_user._version == 2
    assert refreshed_user._event_position == 2

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.account.change_password("new_password")

    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)

    # FIXME This is a bug. Version and event position should be 3
    #   The problem is that the aggregate root is not aware of changes within its child entities
    assert refreshed_user._version == 3
    assert refreshed_user._event_position == 3
