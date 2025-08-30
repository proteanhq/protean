from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import String, ValueObject
from protean.fields.basic import Identifier
from protean.utils import Processing, fqn
from protean.utils.reflection import fields


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_has_metadata_value_object():
    assert "_metadata" in fields(UserLoggedIn)
    assert isinstance(fields(UserLoggedIn)["_metadata"], ValueObject)

    assert hasattr(UserLoggedIn, "_metadata")


def test_metadata_defaults():
    event = UserLoggedIn(user_id=str(uuid4()))
    assert event._metadata is not None
    assert isinstance(event._metadata.headers.time, datetime)


def test_metadata_can_be_overridden():
    now_timestamp = datetime.now() - timedelta(hours=1)
    event = UserLoggedIn(
        user_id=str(uuid4()), _metadata={"headers": {"time": now_timestamp}}
    )
    assert event._metadata is not None
    assert event._metadata.headers.time == now_timestamp


class TestMetadataType:
    def test_metadata_has_type_field(self):
        metadata_field = fields(UserLoggedIn)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "headers")

    def test_command_metadata_type_default(self):
        assert hasattr(UserLoggedIn, "__type__")
        assert UserLoggedIn.__type__ == "Test.UserLoggedIn.v1"

    def test_type_value_in_metadata(self, test_domain):
        user = User(id=str(uuid4()), email="john.doe@gmail.com", name="John Doe")
        user.raise_(UserLoggedIn(user_id=user.id))
        assert user._events[0]._metadata.headers.type == "Test.UserLoggedIn.v1"


class TestMetadataVersion:
    def test_metadata_has_event_version(self):
        metadata_field = fields(UserLoggedIn)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "version")

    def test_event_metadata_version_default(self):
        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.version == "v1"

    def test_overridden_version(self, test_domain):
        class UserLoggedIn(BaseEvent):
            __version__ = "v2"
            user_id = Identifier(identifier=True)

        test_domain.register(UserLoggedIn, part_of=User)
        test_domain.init(traverse=False)

        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.version == "v2"

    def test_version_value_in_multiple_event_definitions(self, test_domain):
        def version1():
            class DummyEvent(BaseEvent):
                user_id = Identifier(identifier=True)

            return DummyEvent

        def version2():
            class DummyEvent(BaseEvent):
                __version__ = "v2"
                user_id = Identifier(identifier=True)

            return DummyEvent

        event_cls1 = version1()
        event_cls2 = version2()

        test_domain.register(event_cls1, part_of=User)
        test_domain.register(event_cls2, part_of=User)
        test_domain.init(traverse=False)

        assert event_cls1.__version__ == "v1"
        assert event_cls2.__version__ == "v2"

        assert len(test_domain.registry.events) == 3  # Includes UserLoggedIn

        assert (
            test_domain.registry.events[fqn(event_cls1)].cls.__type__
            == "Test.DummyEvent.v1"
        )
        assert (
            test_domain.registry.events[fqn(event_cls2)].cls.__type__
            == "Test.DummyEvent.v2"
        )


class TestMetadataAsynchronous:
    def test_metadata_has_asynchronous_field(self):
        metadata_field = fields(UserLoggedIn)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "asynchronous")

    def test_event_metadata_asynchronous_default(self):
        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.asynchronous is True

    def test_event_metadata_asynchronous_override(self, test_domain):
        user = User(id=str(uuid4()), email="john.doe@gmail.com", name="John Doe")
        user.raise_(UserLoggedIn(user_id=user.id))

        # Test Domain event_processing is SYNC by default
        assert user._events[0]._metadata.asynchronous is False

    def test_event_metadata_asynchronous_default_from_domain(self, test_domain):
        # Test Domain event_processing is SYNC by default
        test_domain.config["event_processing"] = Processing.ASYNC.value

        user = User(id=str(uuid4()), email="john.doe@gmail.com", name="John Doe")
        user.raise_(UserLoggedIn(user_id=user.id))

        assert user._events[0]._metadata.asynchronous is True


def test_event_metadata():
    user_id = str(uuid4())
    user = User(id=user_id, email="<EMAIL>", name="<NAME>")

    user.login()

    assert len(user._events) == 1

    event = user._events[0]
    assert event._metadata is not None

    assert isinstance(event._metadata.headers.time, datetime)
    assert event._metadata.headers.id == f"test::user-{user.id}-0"

    assert event.to_dict() == {
        "_metadata": {
            "fqn": fqn(UserLoggedIn),
            "kind": "EVENT",
            "stream": f"test::user-{user.id}",
            "origin_stream": None,
            "version": "v1",
            "sequence_id": "0",
            "payload_hash": event._metadata.payload_hash,
            "asynchronous": False,  # Test Domain event_processing is SYNC by default
            "headers": {
                "id": f"test::user-{user.id}-0",
                "type": "Test.UserLoggedIn.v1",
                "time": str(event._metadata.headers.time),
                "traceparent": None,
            },
        },
        "user_id": event.user_id,
    }
