import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.fields import HasOne, Identifier, String
from protean.utils.eventing import Message


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
        self.raise_(UserActivated(user_id=self.id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.id, name=name))


class UserActivated(BaseEvent):
    user_id = Identifier(identifier=True)


class UserRenamed(BaseEvent):
    user_id = Identifier(identifier=True)
    name = String(required=True, max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, fact_events=True)
    test_domain.register(Account, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(PasswordChanged, part_of=User)
    test_domain.init(traverse=False)


class TestDeltaEvents:
    def test_aggregate_stream_name(self):
        assert User.meta_.stream_category == "test::user"

    def test_event_metadata(self):
        user = User(name="John Doe", email="john.doe@example.com")
        user.change_name("Jane Doe")
        user.activate()

        assert len(user._events) == 2
        assert user._events[0]._metadata.headers.id == f"test::user-{user.id}-0.1"
        assert user._events[0]._metadata.headers.type == "Test.UserRenamed.v1"
        assert user._events[0]._metadata.domain.version == "v1"
        assert user._events[0]._metadata.domain.sequence_id == "0.1"

        assert user._events[1]._metadata.headers.id == f"test::user-{user.id}-0.2"
        assert user._events[1]._metadata.headers.type == "Test.UserActivated.v1"
        assert user._events[1]._metadata.domain.version == "v1"
        assert user._events[1]._metadata.domain.sequence_id == "0.2"

    def test_event_stream_name_in_message(self):
        user = User(name="John Doe", email="john.doe@example.com")
        user.change_name("Jane Doe")

        message = Message.from_domain_object(user._events[0])

        assert message.metadata.headers.stream == f"test::user-{user.id}"

    def test_event_metadata_from_stream(self, test_domain):
        user = User(name="John Doe", email="john.doe@example.com")
        user.change_name("Jane Doe")
        user.activate()

        test_domain.repository_for(User).add(user)

        event_messages = test_domain.event_store.store.read(f"test::user-{user.id}")
        assert len(event_messages) == 2

        assert event_messages[0].metadata.headers.id == f"test::user-{user.id}-0.1"
        assert event_messages[0].metadata.headers.type == "Test.UserRenamed.v1"
        assert event_messages[0].metadata.domain.version == "v1"
        assert event_messages[0].metadata.domain.sequence_id == "0.1"

        assert event_messages[1].metadata.headers.id == f"test::user-{user.id}-0.2"
        assert event_messages[1].metadata.headers.type == "Test.UserActivated.v1"
        assert event_messages[1].metadata.domain.version == "v1"
        assert event_messages[1].metadata.domain.sequence_id == "0.2"
