from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String, ValueObject
from protean.fields.basic import Identifier
from protean.reflection import fields


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_has_metadata_value_object():
    assert "_metadata" in fields(UserLoggedIn)
    assert isinstance(fields(UserLoggedIn)["_metadata"], ValueObject)

    assert hasattr(UserLoggedIn, "_metadata")


def test_metadata_defaults():
    event = UserLoggedIn(user_id=str(uuid4()))
    assert event._metadata is not None
    assert isinstance(event._metadata.timestamp, datetime)


def test_metadata_can_be_overridden():
    now_timestamp = datetime.now() - timedelta(hours=1)
    event = UserLoggedIn(user_id=str(uuid4()), _metadata={"timestamp": now_timestamp})
    assert event._metadata is not None
    assert event._metadata.timestamp == now_timestamp


class TestEventMetadataVersion:
    def test_metadata_has_event_version(self):
        metadata_field = fields(UserLoggedIn)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "version")

    def test_event_metadata_version_default(self):
        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.version == "v1"

    def test_overridden_version(self):
        class UserLoggedIn(BaseEvent):
            __version__ = "v2"
            user_id = Identifier(identifier=True)

        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.version == "v2"


def test_event_metadata():
    user_id = str(uuid4())
    user = User(id=user_id, email="<EMAIL>", name="<NAME>")

    user.login()

    assert len(user._events) == 1

    event = user._events[0]
    assert event._metadata is not None

    assert isinstance(event._metadata.timestamp, datetime)
    assert event._metadata.id == f"Test.User.v1.{user.id}.0"

    assert event.to_dict() == {
        "_metadata": {
            "id": f"Test.User.v1.{user.id}.0",
            "timestamp": str(event._metadata.timestamp),
            "version": "v1",
            "sequence_id": "0",
            "payload_hash": event._metadata.payload_hash,
        },
        "user_id": event.user_id,
    }
