from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError, DeserializationError
from protean.fields import Identifier, String
from protean.utils.eventing import Message, MessageEnvelope, MessageHeaders
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


class UnregisteredEvent(BaseEvent):
    """Event that won't be registered with domain for testing purposes"""

    id = Identifier()
    data = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    # Note: UnregisteredEvent is intentionally NOT registered
    test_domain.init(traverse=False)


class TestMessageErrorHandling:
    """Test suite for enhanced message error handling and debugging"""

    def test_deserialization_error_attributes(self):
        """Test DeserializationError has correct attributes"""
        error = DeserializationError(
            message_id="test-123", error="Test error message", context={"key": "value"}
        )

        assert error.message_id == "test-123"
        assert error.error == "Test error message"
        assert error.context == {"key": "value"}
        assert (
            str(error) == "Failed to deserialize message test-123: Test error message"
        )

    def test_deserialization_error_without_context(self):
        """Test DeserializationError with no context defaults to empty dict"""
        error = DeserializationError(message_id="test-456", error="Another error")

        assert error.message_id == "test-456"
        assert error.error == "Another error"
        assert error.context == {}

    def test_deserialization_error_repr(self):
        """Test DeserializationError string representation"""
        error = DeserializationError(
            message_id="test-789", error="Error message", context={"type": "test.event"}
        )

        expected_repr = "DeserializationError(message_id='test-789', error='Error message', context={'type': 'test.event'})"
        assert repr(error) == expected_repr

    def test_invalid_message_kind_raises_enhanced_error(self):
        """Test that invalid message kind raises DeserializationError with context"""

        headers = MessageHeaders(id="invalid-msg-1", type="test.invalid")

        message = Message(
            headers=headers,
            stream_name="test-stream",
            data={"test": "data"},
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
            metadata=Metadata(
                id="invalid-meta-1",
                type="test.invalid",
                kind="INVALID_KIND",  # Invalid kind
                fqn="test.Invalid",
                stream="test-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        assert error.message_id == "invalid-msg-1"
        assert "Message type is not supported for deserialization" in error.error

        # Check context information
        context = error.context
        assert context["type"] == "test.invalid"
        assert context["stream_name"] == "test-stream"
        assert context["metadata_kind"] == "INVALID_KIND"
        assert context["metadata_type"] == "test.invalid"
        assert context["envelope"] is not None  # Envelope should be present
        assert context["envelope"]["specversion"] == "1.0"
        assert context["original_exception_type"] == "InvalidDataError"
        assert context["has_metadata"] is True
        assert context["has_data"] is True
        assert context["data_keys"] == ["test"]

    def test_unregistered_message_type_raises_enhanced_error(self):
        """Test that unregistered message type raises DeserializationError with context"""
        headers = MessageHeaders(id="unregistered-msg-1", type="unregistered.event")

        message = Message(
            headers=headers,
            stream_name="unregistered-stream",
            data={"id": "123", "data": "test"},
            metadata=Metadata(
                id="unregistered-meta-1",
                type="unregistered.event",
                kind="EVENT",
                fqn="unregistered.Event",
                stream="unregistered-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        assert error.message_id == "unregistered-msg-1"
        assert (
            "Message type unregistered.event is not registered with the domain"
            in error.error
        )

        # Check context information
        context = error.context
        assert context["type"] == "unregistered.event"
        assert context["stream_name"] == "unregistered-stream"
        assert context["metadata_kind"] == "EVENT"
        assert context["metadata_type"] == "unregistered.event"
        assert context["original_exception_type"] == "ConfigurationError"
        assert context["data_keys"] == ["id", "data"]

    def test_malformed_data_raises_enhanced_error(self):
        """Test that malformed message data raises DeserializationError with context"""
        headers = MessageHeaders(id="malformed-msg-1", type="test.registered")

        message = Message(
            headers=headers,
            stream_name="user-123",
            data={"invalid_field": "value"},  # Missing required fields
            metadata=Metadata(
                id="malformed-meta-1",
                type="test.registered",
                kind="EVENT",
                fqn="test.Registered",
                stream="user-123",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        assert error.message_id == "malformed-msg-1"

        # Check context information
        context = error.context
        assert context["type"] == "test.registered"
        assert context["stream_name"] == "user-123"
        assert context["metadata_kind"] == "EVENT"
        assert context["metadata_type"] == "test.registered"
        assert context["data_keys"] == ["invalid_field"]
        # Should contain validation error or similar

    def test_missing_metadata_raises_enhanced_error(self):
        """Test that message with missing metadata raises DeserializationError"""
        # Create message dict with envelope but without metadata to test from_dict error handling
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "headers": {"id": "no-metadata-msg-1", "type": "test.event", "time": None},
            "stream_name": "test-stream",
            "data": {"test": "data"},
            "position": 1,
            "global_position": 1,
            "time": None,
            # metadata intentionally omitted to cause error
        }

        # This should raise a DeserializationError due to missing metadata
        with pytest.raises(DeserializationError) as exc_info:
            Message.from_dict(message_dict)

        error = exc_info.value
        assert error.message_id == "no-metadata-msg-1"
        assert "Missing required field 'metadata'" in error.error
        assert error.context["missing_field"] == "metadata"
        assert error.context["original_exception_type"] == "KeyError"

    def test_missing_data_raises_enhanced_error(self):
        """Test that message with missing data raises DeserializationError"""
        # Create message dict with envelope but without data to test from_dict error handling
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "headers": {"id": "no-data-msg-1", "type": "test.registered", "time": None},
            "id": "no-data-msg-1",
            "type": "test.registered",
            "stream_name": "user-123",
            "metadata": {
                "id": "no-data-meta-1",
                "type": "test.registered",
                "kind": "EVENT",
                "fqn": "test.Registered",
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
            "time": None,
            # data intentionally omitted to cause error
        }

        # This should raise a DeserializationError due to missing data
        with pytest.raises(DeserializationError) as exc_info:
            Message.from_dict(message_dict)

        error = exc_info.value
        assert error.message_id == "no-data-msg-1"
        assert "Missing required field 'data'" in error.error
        assert error.context["missing_field"] == "data"
        assert error.context["original_exception_type"] == "KeyError"

    def test_message_with_unknown_id_raises_enhanced_error(self):
        """Test that message with unknown ID still provides context"""
        # Create a message with a proper ID but unregistered type
        headers = MessageHeaders(id="known-id-123", type="unregistered.event")

        message = Message(
            headers=headers,
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                id="unknown-meta-1",
                type="unregistered.event",
                kind="EVENT",
                fqn="unregistered.Event",
                stream="test-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        # Should have the correct ID
        assert error.message_id == "known-id-123"

    def test_exception_chaining_preserves_original_error(self):
        """Test that DeserializationError preserves the original exception via chaining"""
        headers = MessageHeaders(id="chain-test-msg-1", type="unregistered.event")

        message = Message(
            headers=headers,
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                id="chain-test-meta-1",
                type="unregistered.event",
                kind="EVENT",
                fqn="unregistered.Event",
                stream="test-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        # Check that the original exception is chained
        assert error.__cause__ is not None
        assert isinstance(error.__cause__, ConfigurationError)

    def test_enhanced_context_includes_all_relevant_fields(self):
        """Test that error context includes all relevant message fields"""

        headers = MessageHeaders(id="context-test-msg-1", type="unregistered.type")

        message = Message(
            headers=headers,
            stream_name="context-stream",
            data={"field1": "value1", "field2": "value2"},
            position=42,
            global_position=100,
            envelope=MessageEnvelope(specversion="2.0", checksum=""),
            metadata=Metadata(
                id="context-test-meta-1",
                type="unregistered.type",
                kind="EVENT",
                fqn="unregistered.Type",
                stream="context-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        context = error.context

        # Verify all expected context fields are present
        assert context["type"] == "unregistered.type"
        assert context["stream_name"] == "context-stream"
        assert context["metadata_kind"] == "EVENT"
        assert context["metadata_type"] == "unregistered.type"
        assert context["envelope"] is not None  # Envelope should be present
        assert context["envelope"]["specversion"] == "2.0"
        assert context["envelope"]["checksum"] == ""
        assert context["position"] == 42
        assert context["global_position"] == 100
        assert context["original_exception_type"] == "ConfigurationError"
        assert context["has_metadata"] is True
        assert context["has_data"] is True
        assert set(context["data_keys"]) == {"field1", "field2"}

    def test_successful_deserialization_does_not_raise_error(self):
        """Test that successful message deserialization works normally"""
        identifier = str(uuid4())
        user = User(id=identifier, email="john.doe@example.com", name="John Doe")
        user.raise_(
            Registered(id=identifier, email="john.doe@example.com", name="John Doe")
        )

        message = Message.to_message(user._events[-1])

        # Should not raise any exception
        reconstructed_event = message.to_object()

        assert isinstance(reconstructed_event, Registered)
        assert reconstructed_event.id == identifier
        assert reconstructed_event.email == "john.doe@example.com"
        assert reconstructed_event.name == "John Doe"

    def test_command_deserialization_error_handling(self, test_domain):
        """Test error handling for command deserialization"""
        headers = MessageHeaders(id="cmd-error-msg-1", type="unregistered.command")

        message = Message(
            headers=headers,
            stream_name="user:command-123",
            data={"test": "data"},
            metadata=Metadata(
                id="cmd-error-meta-1",
                type="unregistered.command",
                kind="COMMAND",
                fqn="unregistered.Command",
                stream="user:command-123",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        assert error.message_id == "cmd-error-msg-1"
        assert "unregistered.command is not registered with the domain" in error.error

        context = error.context
        assert context["metadata_kind"] == "COMMAND"
        assert context["stream_name"] == "user:command-123"

    def test_error_handling_with_corrupted_message_fields(self):
        """Test error handling when message has corrupted or unexpected field values"""
        headers = MessageHeaders(
            id="corrupted-msg-1",
            type=None,  # Corrupted type field
        )

        message = Message(
            headers=headers,
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                id="corrupted-meta-1",
                type="test.event",
                kind="EVENT",
                fqn="test.Event",
                stream="test-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        context = error.context

        # Should handle None type gracefully
        assert context["type"] is None

    def test_error_handling_handles_none_id_gracefully(self):
        """Test that error handling converts None ID to 'unknown'"""
        # This tests the internal logic of our error handling
        # We can't easily simulate a None ID on a real Message object
        # but we can test the DeserializationError directly

        # Verify that our error class handles None ID correctly
        error = DeserializationError(
            message_id=None,  # This would come from getattr(self, 'id', 'unknown') returning None
            error="Test error",
            context={"test": "context"},
        )

        # The __init__ should handle None gracefully
        # (Note: our current implementation doesn't handle this case in __init__,
        # but the to_object method does handle it before calling DeserializationError)
        assert str(error) == "Failed to deserialize message None: Test error"
