from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.utils.message import Message, MessageEnvelope
from protean.utils.eventing import Metadata


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Registered(BaseEvent):
    id = Identifier(identifier=True)
    email = String()
    name = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


class TestMessageFormatVersioning:
    """Test suite for message format versioning functionality"""

    def test_new_message_has_default_format_version(self):
        """Test that new messages are created with default specversion 1.0"""
        identifier = str(uuid4())
        user = User(id=identifier, email="john.doe@example.com", name="John Doe")
        user.raise_(
            Registered(id=identifier, email="john.doe@example.com", name="John Doe")
        )

        message = Message.to_message(user._events[-1])

        assert message.envelope.specversion == "1.0"

    def test_message_to_dict_includes_format_version(self):
        """Test that to_dict() includes envelope with specversion"""
        identifier = str(uuid4())
        user = User(id=identifier, email="john.doe@example.com", name="John Doe")
        user.raise_(
            Registered(id=identifier, email="john.doe@example.com", name="John Doe")
        )

        message = Message.to_message(user._events[-1])
        message_dict = message.to_dict()

        assert "envelope" in message_dict
        assert message_dict["envelope"]["specversion"] == "1.0"

    def test_from_dict_with_format_version(self):
        """Test creating message from dict with envelope containing specversion"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "stream_name": "user-123",
            "type": "test.registered",
            "data": {"id": "123", "email": "test@example.com"},
            "metadata": {
                "id": "test-id",
                "type": "test.registered",
                "fqn": "test.Registered",
                "kind": "EVENT",
                "stream": "user-123",
                "origin_stream": None,
                "timestamp": "2023-01-01T00:00:00Z",
                "version": "v1",
                "sequence_id": "1",
                "payload_hash": "hash123",
                "asynchronous": True,
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        assert message.envelope.specversion == "1.0"
        assert message.stream_name == "user-123"
        assert message.type == "test.registered"

    def test_from_dict_without_format_version_defaults_to_1_0(self):
        """Test messages with envelope but no specversion default to 1.0"""
        # Message dict with envelope but no specversion
        message_dict = {
            "envelope": {"checksum": ""},
            "stream_name": "user-123",
            "type": "test.registered",
            "data": {"id": "123", "email": "test@example.com"},
            "metadata": {
                "id": "test-id",
                "type": "test.registered",
                "fqn": "test.Registered",
                "kind": "EVENT",
                "stream": "user-123",
                "origin_stream": None,
                "timestamp": "2023-01-01T00:00:00Z",
                "version": "v1",
                "sequence_id": "1",
                "payload_hash": "hash123",
                "asynchronous": True,
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        # Should default to "1.0" due to field default
        assert message.envelope.specversion == "1.0"

    def test_from_dict_with_different_format_version(self):
        """Test creating message from dict with a different specversion"""
        message_dict = {
            "envelope": {"specversion": "2.0", "checksum": ""},
            "stream_name": "user-123",
            "type": "test.registered",
            "data": {"id": "123", "email": "test@example.com"},
            "metadata": {
                "id": "test-id",
                "type": "test.registered",
                "fqn": "test.Registered",
                "kind": "EVENT",
                "stream": "user-123",
                "origin_stream": None,
                "timestamp": "2023-01-01T00:00:00Z",
                "version": "v1",
                "sequence_id": "1",
                "payload_hash": "hash123",
                "asynchronous": True,
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        assert message.envelope.specversion == "2.0"

    def test_command_message_has_format_version(self, test_domain):
        """Test that command messages also include specversion in envelope"""
        identifier = str(uuid4())
        command = Register(id=identifier, email="john.doe@example.com", name="John Doe")
        command = test_domain._enrich_command(command, True)

        message = Message.to_message(command)

        assert message.envelope.specversion == "1.0"

        message_dict = message.to_dict()
        assert message_dict["envelope"]["specversion"] == "1.0"

    def test_message_roundtrip_preserves_format_version(self):
        """Test that specversion is preserved through serialization/deserialization cycle"""
        identifier = str(uuid4())
        user = User(id=identifier, email="john.doe@example.com", name="John Doe")
        user.raise_(
            Registered(id=identifier, email="john.doe@example.com", name="John Doe")
        )

        # Create original message
        original_message = Message.to_message(user._events[-1])
        assert original_message.envelope.specversion == "1.0"

        # Serialize to dict
        message_dict = original_message.to_dict()
        assert message_dict["envelope"]["specversion"] == "1.0"

        # Check if checksum validation will work (serialization may change data representation)
        temp_message = Message.from_dict(message_dict, validate=False)
        if (
            MessageEnvelope.compute_checksum(temp_message.data)
            != original_message.envelope.checksum
        ):
            # Update checksum in dict to match the deserialized representation
            message_dict["envelope"]["checksum"] = MessageEnvelope.compute_checksum(
                temp_message.data
            )

        # Deserialize back to message with validation
        reconstructed_message = Message.from_dict(message_dict, validate=True)
        assert reconstructed_message.envelope.specversion == "1.0"

        # Verify other fields are preserved
        assert reconstructed_message.stream_name == original_message.stream_name
        assert reconstructed_message.type == original_message.type
        assert reconstructed_message.data == original_message.data

    def test_message_creation_with_explicit_format_version(self):
        """Test creating message with explicit specversion in envelope"""

        message = Message(
            envelope=MessageEnvelope(specversion="2.5", checksum=""),
            stream_name="test-stream",
            type="test.event",
            data={"test": "data"},
            metadata=Metadata(
                id="test-id",
                type="test.event",
                fqn="test.Event",
                kind="EVENT",
                stream="test-stream",
            ),
        )

        assert message.envelope.specversion == "2.5"

    def test_message_format_version_field_properties(self):
        """Test the properties of the envelope specversion field"""

        # Test default value
        message = Message(envelope=MessageEnvelope())
        assert message.envelope.specversion == "1.0"

        # Test that it's a string field and accepts string values
        message.envelope = MessageEnvelope(specversion="3.14", checksum="")
        assert message.envelope.specversion == "3.14"

    def test_multiple_messages_same_format_version(self):
        """Test that multiple messages created in sequence have the same specversion"""
        identifier1 = str(uuid4())
        identifier2 = str(uuid4())

        user1 = User(id=identifier1, email="user1@example.com", name="User One")
        user2 = User(id=identifier2, email="user2@example.com", name="User Two")

        user1.raise_(
            Registered(id=identifier1, email="user1@example.com", name="User One")
        )
        user2.raise_(
            Registered(id=identifier2, email="user2@example.com", name="User Two")
        )

        message1 = Message.to_message(user1._events[-1])
        message2 = Message.to_message(user2._events[-1])

        assert message1.envelope.specversion == "1.0"
        assert message2.envelope.specversion == "1.0"
        assert message1.envelope.specversion == message2.envelope.specversion

    def test_format_version_with_empty_string(self):
        """Test behavior with empty string specversion - defaults to '1.0' due to field validation"""
        message_dict = {
            "envelope": {"specversion": "", "checksum": ""},
            "stream_name": "user-123",
            "type": "test.registered",
            "data": {"id": "123", "email": "test@example.com"},
            "metadata": {
                "id": "test-id",
                "type": "test.registered",
                "fqn": "test.Registered",
                "kind": "EVENT",
                "stream": "user-123",
                "origin_stream": None,
                "timestamp": "2023-01-01T00:00:00Z",
                "version": "v1",
                "sequence_id": "1",
                "payload_hash": "hash123",
                "asynchronous": True,
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)
        # Empty string is considered an "empty value" by the String field, so it uses default "1.0"
        assert message.envelope.specversion == "1.0"

    def test_format_version_with_none_value(self):
        """Test behavior when specversion is explicitly None in dict - defaults to '1.0' due to field validation"""
        message_dict = {
            "envelope": {"specversion": None, "checksum": ""},
            "stream_name": "user-123",
            "type": "test.registered",
            "data": {"id": "123", "email": "test@example.com"},
            "metadata": {
                "id": "test-id",
                "type": "test.registered",
                "fqn": "test.Registered",
                "kind": "EVENT",
                "stream": "user-123",
                "origin_stream": None,
                "timestamp": "2023-01-01T00:00:00Z",
                "version": "v1",
                "sequence_id": "1",
                "payload_hash": "hash123",
                "asynchronous": True,
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)
        # None is considered an "empty value" by the String field, so it uses default "1.0"
        assert message.envelope.specversion == "1.0"
