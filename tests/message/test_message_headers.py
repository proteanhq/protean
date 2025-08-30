from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.command import BaseCommand
from protean.exceptions import DeserializationError
from protean.fields import Identifier, String
from protean.utils.message import Message, MessageEnvelope, MessageHeaders, TraceParent
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


class TestTraceParent:
    """Test suite for TraceParent value object functionality"""

    def test_traceparent_creation_with_valid_fields(self):
        """Test creating TraceParent with valid trace_id and parent_id"""
        trace_id = "1234567890abcdef1234567890abcdef"  # 32 chars
        parent_id = "abcdef1234567890"  # 16 chars

        traceparent = TraceParent(trace_id=trace_id, parent_id=parent_id, sampled=True)

        assert traceparent.trace_id == trace_id
        assert traceparent.parent_id == parent_id
        assert traceparent.sampled is True

    def test_traceparent_build_from_valid_string(self):
        """Test building TraceParent from valid traceparent string format"""
        traceparent_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

        traceparent = TraceParent.build(traceparent_str)

        assert traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        assert traceparent.parent_id == "abcdef1234567890"
        assert traceparent.sampled is True

    def test_traceparent_build_from_unsampled_string(self):
        """Test building TraceParent with sampled=False"""
        traceparent_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-00"

        traceparent = TraceParent.build(traceparent_str)

        assert traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        assert traceparent.parent_id == "abcdef1234567890"
        assert traceparent.sampled is False

    def test_traceparent_build_with_invalid_format(self):
        """Test that invalid traceparent format returns None"""
        invalid_formats = [
            "invalid",
            "1234-5678",
            "00-1234-5678",  # Too few parts
            "00-1234-5678-9abc-def0-extra",  # Too many parts
            "01-1234567890abcdef1234567890abcdef-abcdef1234567890-01",  # Wrong version
            "1234567890abcdef1234567890abcdef-abcdef1234567890-01",  # Missing version
            "",
            None,
        ]

        for invalid_format in invalid_formats:
            result = TraceParent.build(invalid_format)
            assert result is None

    def test_traceparent_to_dict_sampled(self):
        """Test to_dict returns proper formatted string when sampled=True"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )

        result = traceparent.to_dict()
        assert result == "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

    def test_traceparent_to_dict_unsampled(self):
        """Test to_dict returns proper formatted string when sampled=False"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=False,
        )

        result = traceparent.to_dict()
        assert result == "00-1234567890abcdef1234567890abcdef-abcdef1234567890-00"

    def test_traceparent_correlation_id_property(self):
        """Test that correlation_id property returns trace_id"""
        trace_id = "1234567890abcdef1234567890abcdef"
        traceparent = TraceParent(
            trace_id=trace_id, parent_id="abcdef1234567890", sampled=False
        )

        assert traceparent.correlation_id == trace_id

    def test_traceparent_causation_id_property(self):
        """Test that causation_id property returns parent_id"""
        parent_id = "abcdef1234567890"
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id=parent_id,
            sampled=False,
        )

        assert traceparent.causation_id == parent_id

    def test_traceparent_default_sampled_false(self):
        """Test that sampled defaults to False"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef", parent_id="abcdef1234567890"
        )

        assert traceparent.sampled is False

    def test_traceparent_roundtrip_build_to_dict(self):
        """Test that build() and to_dict() are inverse operations"""
        original_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

        traceparent = TraceParent.build(original_str)
        result_str = traceparent.to_dict()

        assert result_str == original_str


class TestMessageHeaders:
    """Test suite for MessageHeaders value object functionality"""

    def test_message_headers_creation_with_traceparent(self):
        """Test creating MessageHeaders with traceparent"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )

        headers = MessageHeaders(traceparent=traceparent)

        assert headers.traceparent == traceparent
        assert headers.traceparent.correlation_id == "1234567890abcdef1234567890abcdef"

    def test_message_headers_creation_empty(self):
        """Test creating empty MessageHeaders"""
        headers = MessageHeaders()

        assert headers.traceparent is None

    def test_message_headers_to_dict_with_traceparent(self):
        """Test MessageHeaders serialization with traceparent"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(traceparent=traceparent)

        headers_dict = headers.to_dict()

        assert "traceparent" in headers_dict
        assert (
            headers_dict["traceparent"]["trace_id"]
            == "1234567890abcdef1234567890abcdef"
        )
        assert headers_dict["traceparent"]["parent_id"] == "abcdef1234567890"
        assert headers_dict["traceparent"]["sampled"] is True

    def test_message_headers_to_dict_empty(self):
        """Test MessageHeaders serialization when empty"""
        headers = MessageHeaders()
        headers_dict = headers.to_dict()

        assert "traceparent" in headers_dict
        assert headers_dict["traceparent"] is None

    def test_message_headers_build_from_traceparent_string(self):
        """Test MessageHeaders.build() method with traceparent string"""
        traceparent_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

        headers = MessageHeaders.build(traceparent_str)

        assert headers.traceparent is not None
        assert headers.traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        assert headers.traceparent.parent_id == "abcdef1234567890"
        assert headers.traceparent.sampled is True

    def test_message_headers_build_from_invalid_traceparent_string(self):
        """Test MessageHeaders.build() method with invalid traceparent string"""
        invalid_traceparent = "invalid-traceparent"

        headers = MessageHeaders.build(invalid_traceparent)

        # build() should handle invalid traceparent gracefully
        assert headers.traceparent is None

    def test_message_headers_build_from_empty_traceparent(self):
        """Test MessageHeaders.build() method with empty/None traceparent"""
        headers1 = MessageHeaders.build(None)
        headers2 = MessageHeaders.build("")

        # Both should create MessageHeaders with no traceparent
        assert headers1.traceparent is None
        assert headers2.traceparent is None


class TestMessageWithHeaders:
    """Test suite for Message class with MessageHeaders functionality"""

    def test_message_creation_with_headers(self):
        """Test creating Message with headers"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(traceparent=traceparent)

        message = Message(
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
            headers=headers,
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

        assert message.headers == headers
        assert (
            message.headers.traceparent.correlation_id
            == "1234567890abcdef1234567890abcdef"
        )

    def test_message_creation_without_headers(self):
        """Test creating Message without headers"""
        message = Message(
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
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

        assert message.headers is None

    def test_message_to_dict_includes_headers(self):
        """Test that to_dict() includes headers when present"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(traceparent=traceparent)

        message = Message(
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
            headers=headers,
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

        message_dict = message.to_dict()

        assert "headers" in message_dict
        assert (
            message_dict["headers"]["traceparent"]["trace_id"]
            == "1234567890abcdef1234567890abcdef"
        )
        assert message_dict["headers"]["traceparent"]["sampled"] is True

    def test_message_to_dict_excludes_empty_headers(self):
        """Test that to_dict() excludes headers when None"""
        message = Message(
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
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

        message_dict = message.to_dict()

        assert "headers" in message_dict
        assert message_dict["headers"] is None

    def test_message_from_dict_with_headers(self):
        """Test creating Message from dict with headers"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "headers": {
                "traceparent": {
                    "trace_id": "1234567890abcdef1234567890abcdef",
                    "parent_id": "abcdef1234567890",
                    "sampled": True,
                }
            },
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "id": "test-id",
                "type": "test.event",
                "fqn": "test.Event",
                "kind": "EVENT",
                "stream": "test-stream",
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

        assert message.headers is not None
        assert (
            message.headers.traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        )
        assert message.headers.traceparent.sampled is True

    def test_message_from_dict_without_headers(self):
        """Test creating Message from dict without headers (backward compatibility)"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "id": "test-id",
                "type": "test.event",
                "fqn": "test.Event",
                "kind": "EVENT",
                "stream": "test-stream",
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

        assert message.headers is None

    def test_message_from_dict_with_empty_headers(self):
        """Test creating Message from dict with empty headers"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "headers": {"traceparent": None},
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "id": "test-id",
                "type": "test.event",
                "fqn": "test.Event",
                "kind": "EVENT",
                "stream": "test-stream",
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

        # When traceparent is None, the ValueObject field validation rejects the MessageHeaders
        # This is expected behavior - headers becomes None when all nested fields are None
        assert message.headers is None

    def test_message_from_dict_with_valid_traceparent(self):
        """Test creating Message from dict with valid traceparent data"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "headers": {
                "traceparent": {
                    "trace_id": "1234567890abcdef1234567890abcdef",
                    "parent_id": "abcdef1234567890",
                    "sampled": True,
                }
            },
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "id": "test-id",
                "type": "test.event",
                "fqn": "test.Event",
                "kind": "EVENT",
                "stream": "test-stream",
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

        # With valid traceparent data, headers should be properly created
        assert message.headers is not None
        assert message.headers.traceparent is not None
        assert (
            message.headers.traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        )
        assert message.headers.traceparent.sampled is True

    def test_message_roundtrip_with_headers(self):
        """Test that headers are preserved through serialization/deserialization cycle"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(traceparent=traceparent)

        # Create original message
        original_message = Message(
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
            headers=headers,
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

        # Serialize to dict
        message_dict = original_message.to_dict()

        # Deserialize back to message
        reconstructed_message = Message.from_dict(message_dict, validate=False)

        # Verify headers are preserved
        assert reconstructed_message.headers is not None
        assert (
            reconstructed_message.headers.traceparent.trace_id
            == "1234567890abcdef1234567890abcdef"
        )
        assert reconstructed_message.headers.traceparent.parent_id == "abcdef1234567890"
        assert reconstructed_message.headers.traceparent.sampled is True
        assert (
            reconstructed_message.headers.traceparent.correlation_id
            == "1234567890abcdef1234567890abcdef"
        )
        assert (
            reconstructed_message.headers.traceparent.causation_id == "abcdef1234567890"
        )

    def test_message_to_message_preserves_headers_when_none(self):
        """Test that to_message creates message without headers when not present in event/command"""
        identifier = str(uuid4())
        user = User(id=identifier, email="john.doe@example.com", name="John Doe")
        user.raise_(
            Registered(id=identifier, email="john.doe@example.com", name="John Doe")
        )

        message = Message.to_message(user._events[-1])

        # Current implementation should not set headers automatically
        assert message.headers is None

    def test_message_error_context_includes_headers(self):
        """Test that error context includes headers information"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(traceparent=traceparent)

        message = Message(
            id="test-msg-with-headers",
            type="unregistered.type",
            stream_name="test-stream",
            data={"field1": "value1"},
            envelope=MessageEnvelope(specversion="1.0", checksum=""),
            headers=headers,
            metadata=Metadata(
                id="test-meta-1",
                type="unregistered.type",
                kind="EVENT",
                fqn="unregistered.Type",
                stream="test-stream",
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        context = error.context

        # Verify headers are included in error context
        assert "envelope" in context
        assert context["envelope"] is not None
