from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier
from protean.testing import given
from protean.utils import Processing, fqn
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import g


class UserLoggedIn(BaseEvent):
    user_id: Identifier(identifier=True)


class Login(BaseCommand):
    user_id: Identifier(identifier=True)


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))

    @apply
    def on_logged_in(self, event: UserLoggedIn) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.register(Login, part_of=User)
    test_domain.init(traverse=False)


def test_event_has_metadata_value_object():
    # _metadata is a private attribute, not in fields()
    assert hasattr(UserLoggedIn, "_metadata")


def test_metadata_defaults():
    event = UserLoggedIn(user_id=str(uuid4()))
    assert event._metadata is not None
    assert isinstance(event._metadata.headers.time, datetime)


def test_metadata_can_be_overridden():
    now_timestamp = datetime.now(UTC) - timedelta(hours=1)
    event = UserLoggedIn(
        user_id=str(uuid4()),
        _metadata=Metadata(
            headers=MessageHeaders(time=now_timestamp),
        ),
    )
    assert event._metadata is not None
    assert event._metadata.headers.time == now_timestamp


class TestMetadataType:
    def test_metadata_has_type_field(self):
        # _metadata is now a PrivateAttr; verify Metadata class has headers
        assert hasattr(Metadata, "model_fields")
        assert "headers" in Metadata.model_fields

    def test_command_metadata_type_default(self):
        assert hasattr(UserLoggedIn, "__type__")
        assert UserLoggedIn.__type__ == "Test.UserLoggedIn.v1"

    def test_type_value_in_metadata(self, test_domain):
        user = User(id=str(uuid4()), email="john.doe@gmail.com", name="John Doe")
        user.raise_(UserLoggedIn(user_id=user.id))
        assert user._events[0]._metadata.headers.type == "Test.UserLoggedIn.v1"


class TestMetadataVersion:
    def test_metadata_has_event_version(self):
        # _metadata is now a PrivateAttr; verify Metadata class has domain
        assert "domain" in Metadata.model_fields
        assert hasattr(DomainMeta, "model_fields")
        assert "version" in DomainMeta.model_fields

    def test_event_metadata_version_default(self):
        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.domain.version == 1

    def test_overridden_version(self, test_domain):
        class UserLoggedIn(BaseEvent):
            __version__ = 2
            user_id: Identifier(identifier=True)

        test_domain.register(UserLoggedIn, part_of=User)
        test_domain.init(traverse=False)

        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.domain.version == 2

    def test_version_value_in_multiple_event_definitions(self, test_domain):
        def version1():
            class DummyEvent(BaseEvent):
                user_id: Identifier(identifier=True)

            return DummyEvent

        def version2():
            class DummyEvent(BaseEvent):
                __version__ = 2
                user_id: Identifier(identifier=True)

            return DummyEvent

        event_cls1 = version1()
        event_cls2 = version2()

        test_domain.register(event_cls1, part_of=User)
        test_domain.register(event_cls2, part_of=User)
        test_domain.init(traverse=False)

        assert event_cls1.__version__ == 1
        assert event_cls2.__version__ == 2

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
        # _metadata is now a PrivateAttr; verify DomainMeta has asynchronous
        assert "domain" in Metadata.model_fields
        assert "asynchronous" in DomainMeta.model_fields

    def test_event_metadata_asynchronous_default(self):
        event = UserLoggedIn(user_id=str(uuid4()))
        assert event._metadata.domain.asynchronous is True

    def test_event_metadata_asynchronous_override(self, test_domain):
        user = User(id=str(uuid4()), email="john.doe@gmail.com", name="John Doe")
        user.raise_(UserLoggedIn(user_id=user.id))

        # Test Domain event_processing is SYNC by default
        assert user._events[0]._metadata.domain.asynchronous is False

    def test_event_metadata_asynchronous_default_from_domain(self, test_domain):
        # Test Domain event_processing is SYNC by default
        test_domain.config["event_processing"] = Processing.ASYNC.value

        user = User(id=str(uuid4()), email="john.doe@gmail.com", name="John Doe")
        user.raise_(UserLoggedIn(user_id=user.id))

        assert user._events[0]._metadata.domain.asynchronous is True


def test_event_metadata():
    user_id = str(uuid4())
    user = User(id=user_id, email="<EMAIL>", name="<NAME>")

    user.login()

    assert len(user._events) == 1

    event = user._events[0]
    assert event._metadata is not None

    assert isinstance(event._metadata.headers.time, datetime)
    assert event._metadata.headers.id == f"test::user-{user.id}-0"

    # Compute expected checksum
    expected_checksum = MessageEnvelope.compute_checksum(event.payload)

    assert event.to_dict() == {
        "_metadata": {
            "domain": {
                "fqn": fqn(UserLoggedIn),
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "test::user",
                "version": 1,
                "sequence_id": "0",
                "asynchronous": False,  # Test Domain event_processing is SYNC by default
                "expected_version": None,
                "priority": 0,
                "correlation_id": None,
                "causation_id": None,
            },
            "envelope": {
                "specversion": "1.0",
                "checksum": expected_checksum,
            },
            "headers": {
                "id": f"test::user-{user.id}-0",
                "type": "Test.UserLoggedIn.v1",
                "stream": f"test::user-{user.id}",
                "time": event._metadata.headers.time.isoformat(),
                "traceparent": None,
                "idempotency_key": None,
                "deadline": None,
            },
            "event_store": None,
            "extensions": {},
        },
        "user_id": event.user_id,
    }


class TestEnvelopeMetadata:
    """Comprehensive tests for envelope attribute in event metadata."""

    def test_envelope_is_always_present(self, test_domain):
        """Test that envelope is always present in event metadata."""
        user = User(id=str(uuid4()), email="test@example.com", name="Test User")
        user.raise_(UserLoggedIn(user_id=user.id))

        event = user._events[0]
        assert event._metadata.envelope is not None

    def test_envelope_has_specversion(self, test_domain):
        """Test that envelope has the correct specversion."""
        user = User(id=str(uuid4()), email="test@example.com", name="Test User")
        user.raise_(UserLoggedIn(user_id=user.id))

        event = user._events[0]
        assert event._metadata.envelope.specversion == "1.0"

    def test_envelope_has_valid_checksum(self, test_domain):
        """Test that envelope has a valid checksum."""
        user = User(id=str(uuid4()), email="test@example.com", name="Test User")
        user.raise_(UserLoggedIn(user_id=user.id))

        event = user._events[0]
        assert event._metadata.envelope.checksum is not None
        assert isinstance(event._metadata.envelope.checksum, str)
        assert len(event._metadata.envelope.checksum) == 64  # SHA256 hex digest length

    def test_envelope_checksum_matches_payload(self, test_domain):
        """Test that envelope checksum correctly matches the event payload."""
        user_id = str(uuid4())
        user = User(id=user_id, email="test@example.com", name="Test User")
        user.raise_(UserLoggedIn(user_id=user_id))

        event = user._events[0]
        expected_checksum = MessageEnvelope.compute_checksum(event.payload)
        assert event._metadata.envelope.checksum == expected_checksum

    def test_envelope_checksum_changes_with_different_payload(self, test_domain):
        """Test that different payloads result in different checksums."""
        user1 = User(id=str(uuid4()), email="user1@example.com", name="User One")
        user2 = User(id=str(uuid4()), email="user2@example.com", name="User Two")

        user1.raise_(UserLoggedIn(user_id=user1.id))
        user2.raise_(UserLoggedIn(user_id=user2.id))

        event1 = user1._events[0]
        event2 = user2._events[0]

        # Different payloads should have different checksums
        assert event1._metadata.envelope.checksum != event2._metadata.envelope.checksum

    def test_envelope_in_multiple_events(self, test_domain):
        """Test that envelope is correctly set for multiple events."""
        user = User(id=str(uuid4()), email="test@example.com", name="Test User")

        # Raise multiple events
        for _ in range(3):
            user.raise_(UserLoggedIn(user_id=user.id))

        assert len(user._events) == 3

        # Each event should have envelope with valid checksum
        for event in user._events:
            assert event._metadata.envelope is not None
            assert event._metadata.envelope.specversion == "1.0"
            assert event._metadata.envelope.checksum is not None
            assert len(event._metadata.envelope.checksum) == 64

    def test_envelope_in_to_dict_output(self, test_domain):
        """Test that envelope appears correctly in to_dict output."""
        user = User(id=str(uuid4()), email="test@example.com", name="Test User")
        user.raise_(UserLoggedIn(user_id=user.id))

        event = user._events[0]
        event_dict = event.to_dict()

        assert "_metadata" in event_dict
        assert "envelope" in event_dict["_metadata"]
        assert "specversion" in event_dict["_metadata"]["envelope"]
        assert "checksum" in event_dict["_metadata"]["envelope"]
        assert event_dict["_metadata"]["envelope"]["specversion"] == "1.0"
        assert event_dict["_metadata"]["envelope"]["checksum"] is not None

    def test_envelope_preservation_through_serialization(self, test_domain):
        """Test that envelope metadata is preserved through serialization/deserialization."""
        user = User(id=str(uuid4()), email="test@example.com", name="Test User")
        user.raise_(UserLoggedIn(user_id=user.id))

        original_event = user._events[0]
        original_envelope = original_event._metadata.envelope

        # Serialize and create new event
        event_dict = original_event.to_dict()

        # Verify envelope in dictionary
        assert (
            event_dict["_metadata"]["envelope"]["checksum"]
            == original_envelope.checksum
        )
        assert (
            event_dict["_metadata"]["envelope"]["specversion"]
            == original_envelope.specversion
        )


def test_trace_ids_survive_rebuilding_an_event_from_its_metadata():
    original = UserLoggedIn(user_id=str(uuid4()))
    domain = original._metadata.domain.model_copy(
        update={"correlation_id": "checkout-42", "causation_id": "cmd-1"}
    )
    metadata = original._metadata.model_copy(update={"domain": domain})

    rebuilt = UserLoggedIn(_metadata=metadata, user_id=original.user_id)

    assert rebuilt._metadata.domain.correlation_id == "checkout-42"
    assert rebuilt._metadata.domain.causation_id == "cmd-1"


def _raised_event(correlation_id=None, causation_id=None):
    user = User(id=str(uuid4()), email="john@example.com", name="John")
    user.login()
    event = user._events[-1]
    if correlation_id is None and causation_id is None:
        return event
    domain = event._metadata.domain.model_copy(
        update={"correlation_id": correlation_id, "causation_id": causation_id}
    )
    metadata = event._metadata.model_copy(update={"domain": domain})
    return UserLoggedIn(event.payload, _metadata=metadata)


@contextmanager
def _in_context(message):
    g.message_in_context = message
    try:
        yield message
    finally:
        g.pop("message_in_context", None)


def _other_message():
    return Message.from_domain_object(
        _raised_event(correlation_id="corr-X", causation_id="cause-X")
    )


class TestTraceIdsOnRebuildFromStoredMessage:
    def test_root_event_keeps_empty_trace_ids(self):
        root = _raised_event()
        assert root._metadata.domain.correlation_id is None
        assert root._metadata.domain.causation_id is None
        stored = Message.from_domain_object(root)

        with _in_context(_other_message()):
            rebuilt = stored.to_domain_object()

        assert rebuilt._metadata.domain.correlation_id is None
        assert rebuilt._metadata.domain.causation_id is None

    def test_stored_trace_ids_win_over_context(self):
        stored = Message.from_domain_object(
            _raised_event(correlation_id="checkout-42", causation_id="cmd-1")
        )

        with _in_context(_other_message()):
            rebuilt = stored.to_domain_object()

        assert rebuilt._metadata.domain.correlation_id == "checkout-42"
        assert rebuilt._metadata.domain.causation_id == "cmd-1"

    def test_message_in_context_does_not_cause_itself(self):
        stored = Message.from_domain_object(_raised_event())

        with _in_context(stored):
            rebuilt = stored.to_domain_object()

        assert stored.metadata.headers.id is not None
        assert rebuilt._metadata.domain.causation_id != stored.metadata.headers.id
        assert rebuilt._metadata.domain.causation_id is None
        assert rebuilt._metadata.domain.correlation_id is None

    def test_direct_construction_still_inherits_context_trace_ids(self):
        # Process manager transitions and seeded test events pass metadata
        # with no trace IDs and rely on the context to fill them in.
        root = _raised_event()

        with _in_context(_other_message()) as other:
            event = UserLoggedIn(root.payload, _metadata=root._metadata)

        assert event._metadata.domain.correlation_id == "corr-X"
        assert event._metadata.domain.causation_id == other.metadata.headers.id

    def test_stored_correlation_with_empty_causation_keeps_causation_empty(self):
        stored = Message.from_domain_object(
            _raised_event(correlation_id="checkout-42", causation_id=None)
        )

        with _in_context(_other_message()):
            rebuilt = stored.to_domain_object()

        assert rebuilt._metadata.domain.correlation_id == "checkout-42"
        assert rebuilt._metadata.domain.causation_id is None

    def test_seeded_event_inherits_context_trace_ids(self, test_domain):
        root = _raised_event()
        result = given(User, root)

        with _in_context(_other_message()) as other:
            aggregate_id = result._seed_events(test_domain)

        messages = test_domain.event_store.store.read(f"test::user-{aggregate_id}")
        assert len(messages) == 1
        assert messages[0].metadata.domain.correlation_id == "corr-X"
        assert messages[0].metadata.domain.causation_id == other.metadata.headers.id

    def test_rebuild_flag_in_template_dict_is_not_a_field(self):
        root = _raised_event()

        with _in_context(_other_message()) as other:
            event = UserLoggedIn(
                {**root.payload, "_rebuild": True}, _metadata=root._metadata
            )

        assert event.user_id == root.user_id
        assert "_rebuild" not in event.to_dict()
        # A `_rebuild` key in the template dict does not switch on rebuild
        assert event._metadata.domain.correlation_id == "corr-X"
        assert event._metadata.domain.causation_id == other.metadata.headers.id


def _with_origin_stream(event, origin_stream):
    message = Message.from_domain_object(event)
    domain = message.metadata.domain.model_copy(update={"origin_stream": origin_stream})
    metadata = message.metadata.model_copy(update={"domain": domain})
    return message.model_copy(update={"metadata": metadata})


def _command_from_stream_b(test_domain):
    command = test_domain._command_processor.enrich(
        Login(user_id=str(uuid4())), asynchronous=True
    )
    message = Message.from_domain_object(command)
    domain = message.metadata.domain.model_copy(
        update={"origin_stream": "test::stream-b"}
    )
    metadata = message.metadata.model_copy(update={"domain": domain})
    message = message.model_copy(update={"metadata": metadata})
    # Events built while handling this command take its origin stream
    assert message.metadata.domain.kind == "COMMAND"
    assert message.metadata.domain.origin_stream == "test::stream-b"
    return message


class TestOriginStreamOnRebuildFromStoredMessage:
    def test_stored_origin_stream_wins_over_context(self, test_domain):
        stored = _with_origin_stream(_raised_event(), "test::stream-a")
        assert stored.metadata.domain.origin_stream == "test::stream-a"

        with _in_context(_command_from_stream_b(test_domain)):
            rebuilt = stored.to_domain_object()

        assert rebuilt._metadata.domain.origin_stream == "test::stream-a"

    def test_empty_stored_origin_stream_stays_empty(self, test_domain):
        stored = _with_origin_stream(_raised_event(), None)
        assert stored.metadata.domain.origin_stream is None

        with _in_context(_command_from_stream_b(test_domain)):
            rebuilt = stored.to_domain_object()

        assert rebuilt._metadata.domain.origin_stream is None

    def test_stored_origin_stream_kept_with_no_message_in_context(self):
        stored = _with_origin_stream(_raised_event(), "test::stream-a")

        rebuilt = stored.to_domain_object()

        assert rebuilt._metadata.domain.origin_stream == "test::stream-a"

    def test_direct_construction_still_takes_origin_stream_from_context(
        self, test_domain
    ):
        root = _raised_event()

        with _in_context(_command_from_stream_b(test_domain)):
            event = UserLoggedIn(root.payload, _metadata=root._metadata)

        assert event._metadata.domain.origin_stream == "test::stream-b"

    def test_rebuild_flag_in_template_dict_does_not_keep_origin_stream(
        self, test_domain
    ):
        stored = _with_origin_stream(_raised_event(), "test::stream-a")
        root = stored.to_domain_object()

        with _in_context(_command_from_stream_b(test_domain)):
            event = UserLoggedIn(
                {**root.payload, "_rebuild": True}, _metadata=root._metadata
            )

        assert event._metadata.domain.origin_stream == "test::stream-b"
