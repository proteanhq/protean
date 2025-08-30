import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasOne, Identifier, String


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
    status = String(choices=["ACTIVE", "ARCHIVED"])

    account = HasOne(Account)

    def activate(self):
        self.status = "ACTIVE"
        self.raise_(UserActivated(user_id=self.id))

    def change_name(self, name):
        self.name = name
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


def test_initialization_with_first_event():
    user = User(name="John Doe", email="john.doe@example.com")
    user.activate()

    assert user._events[0]._metadata.headers.id == f"test::user-{user.id}-0.1"
    assert user._events[0]._metadata.sequence_id == "0.1"


def test_initialization_with_multiple_events():
    user = User(name="John Doe", email="john.doe@example.com")
    user.activate()
    user.change_name("Jane Doe")

    assert user._events[0]._metadata.headers.id == f"test::user-{user.id}-0.1"
    assert user._events[0]._metadata.sequence_id == "0.1"
    assert user._events[1]._metadata.headers.id == f"test::user-{user.id}-0.2"
    assert user._events[1]._metadata.sequence_id == "0.2"


def test_one_event_after_persistence(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    user.activate()
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_name("Jane Doe")

    assert (
        refreshed_user._events[0]._metadata.headers.id
        == f"test::user-{refreshed_user.id}-1.1"
    )
    assert refreshed_user._events[0]._metadata.sequence_id == "1.1"


def test_multiple_events_after_persistence(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    user.activate()
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_name("Jane Doe")
    refreshed_user.change_name("Baby Doe")

    assert (
        refreshed_user._events[0]._metadata.headers.id
        == f"test::user-{refreshed_user.id}-1.1"
    )
    assert refreshed_user._events[0]._metadata.sequence_id == "1.1"
    assert (
        refreshed_user._events[1]._metadata.headers.id
        == f"test::user-{refreshed_user.id}-1.2"
    )
    assert refreshed_user._events[1]._metadata.sequence_id == "1.2"


def test_multiple_events_after_multiple_persistence(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    user.activate()
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_name("Jane Doe")
    refreshed_user.change_name("Baby Doe")
    test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.change_name("Ark Doe")
    refreshed_user.change_name("Zing Doe")

    assert (
        refreshed_user._events[0]._metadata.headers.id
        == f"test::user-{refreshed_user.id}-2.1"
    )
    assert refreshed_user._events[0]._metadata.sequence_id == "2.1"
    assert (
        refreshed_user._events[1]._metadata.headers.id
        == f"test::user-{refreshed_user.id}-2.2"
    )
    assert refreshed_user._events[1]._metadata.sequence_id == "2.2"
