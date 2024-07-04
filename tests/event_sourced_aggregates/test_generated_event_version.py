from enum import Enum

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate, apply
from protean.fields import Identifier, String
from protean.utils.mixins import Message


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


def test_aggregate_and_event_version_on_initialization():
    user = User.register(user_id="1", name="John Doe", email="john.doe@example.com")
    assert user._version == 0
    assert user._events[0]._metadata.id.endswith("-0")
    assert user._events[0]._metadata.sequence_id == "0"


def test_aggregate_and_event_version_after_first_persistence(test_domain):
    user = User.register(user_id="1", name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    event_messages = test_domain.event_store.store.read(f"user-{user.user_id}")
    assert len(event_messages) == 1

    refreshed_user = test_domain.repository_for(User).get(user.user_id)
    assert refreshed_user._version == 0

    # Deserialize event
    event = Message.to_object(event_messages[0])

    assert event._metadata.id.endswith("-0")
    assert event._metadata.sequence_id == "0"


def test_aggregate_and_event_version_after_first_persistence_after_multiple_persistence(
    test_domain,
):
    user = User.register(user_id="1", name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    for i in range(10):
        refreshed_user = test_domain.repository_for(User).get(user.user_id)
        refreshed_user.change_name(f"John Doe {i}")
        test_domain.repository_for(User).add(refreshed_user)

    event_messages = test_domain.event_store.store.read(f"user-{user.user_id}")
    assert len(event_messages) == 11

    refreshed_user = test_domain.repository_for(User).get(user.user_id)
    assert refreshed_user._version == 10

    # Deserialize event
    event = Message.to_object(event_messages[-1])

    assert event._metadata.id.endswith("-10")
    assert event._metadata.sequence_id == "10"


def test_aggregate_and_event_version_after_multiple_event_generation_in_one_update_cylce(
    test_domain,
):
    user = User.register(user_id="1", name="John Doe", email="john.doe@example.com")
    user.change_name("Jane Doe")

    # Check event versions before persistence
    assert user._version == 1
    assert user._events[0]._metadata.id.endswith("-0")
    assert user._events[0]._metadata.sequence_id == "0"
    assert user._events[1]._metadata.id.endswith("-1")
    assert user._events[1]._metadata.sequence_id == "1"

    # Persist user just once
    test_domain.repository_for(User).add(user)

    # Retrieve user
    refreshed_user = test_domain.repository_for(User).get(user.user_id)

    assert refreshed_user._version == 1

    event_messages = test_domain.event_store.store.read(f"user-{user.user_id}")
    assert len(event_messages) == 2

    event1 = Message.to_object(event_messages[0])
    event2 = Message.to_object(event_messages[1])

    assert event1._metadata.id.endswith("-0")
    assert event1._metadata.sequence_id == "0"
    assert event2._metadata.id.endswith("-1")
    assert event2._metadata.sequence_id == "1"
